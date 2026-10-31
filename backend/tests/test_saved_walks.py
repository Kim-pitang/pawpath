"""나만의 산책길 API. 지시서의 예외 항목을 서버 쪽에서 검증한다."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, inspect, select, text

from app import api as api_module
from app.database import SessionLocal, engine
from app.main import MAX_REQUEST_BYTES
from app.migrations import ensure_schema
from app.models import SavedWalk, SavedWalkPoint
from app.services.gpx_service import GpxPoint
from app.services.saved_walk_service import haversine_m, split_impossible_jumps
from tests.test_api_e2e import dubu_id

START = datetime(2026, 10, 31, 16, 0, 0)


def track(count=5, lat=37.4882, lng=127.0647, step=0.0003, segment=0, start=START, seconds=20):
    return [
        {
            "latitude": lat + step * index,
            "longitude": lng,
            "recorded_at": (start + timedelta(seconds=seconds * index)).isoformat(),
            "accuracy": 8,
            "segment": segment,
        }
        for index in range(count)
    ]


def save(client, **overrides):
    body = {"title": "저녁 산책", "points": track(), **overrides}
    response = client.post("/api/my-walks", json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


def gpx(body: str) -> bytes:
    return f'<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">{body}</gpx>'.encode()


TIMED_GPX = gpx(
    """<trk><name>가져온 길</name><trkseg>
    <trkpt lat="37.5" lon="127"><ele>10</ele><time>2026-10-30T01:00:00Z</time></trkpt>
    <trkpt lat="37.501" lon="127"><ele>11</ele><time>2026-10-30T01:01:00Z</time></trkpt>
    <trkpt lat="37.502" lon="127"><time>2026-10-30T01:02:00Z</time></trkpt></trkseg></trk>"""
)


def preview(client, data=TIMED_GPX):
    return client.post("/api/my-walks/import/preview", content=data, headers={"Content-Type": "application/gpx+xml"})


def imported(client, data=TIMED_GPX, **overrides):
    body = preview(client, data).json()
    return save(client, title=body["name"] or "가져온 길", source_type="imported", points=body["points"], **overrides)


# ---------- 저장과 계산
def test_saving_a_recorded_walk_computes_distance_on_the_server(client):
    walk = save(client, pet_id=dubu_id(client), memo="날씨 좋음", duration_sec=80)
    expected = sum(haversine_m(37.4882 + 0.0003 * i, 127.0647, 37.4882 + 0.0003 * (i + 1), 127.0647) for i in range(4))
    assert walk["distance_m"] == pytest.approx(expected, abs=0.1)
    assert walk["duration_sec"] == 80
    assert walk["average_speed_mps"] == pytest.approx(expected / 80, abs=0.01)
    assert walk["point_count"] == 5
    assert walk["visibility"] == "private"
    assert walk["share_token"] is None
    assert walk["pet_name"] == "두부"
    assert walk["started_at"] == START.isoformat()
    assert walk["source_type"] == "recorded"
    assert len(walk["route"]) == 1


def test_points_are_stored_separately_in_order(client):
    walk = save(client)
    with SessionLocal() as db:
        rows = list(db.scalars(select(SavedWalkPoint).where(SavedWalkPoint.walk_id == walk["id"]).order_by(SavedWalkPoint.sequence)))
    assert [row.sequence for row in rows] == [0, 1, 2, 3, 4]
    assert rows[0].accuracy == 8
    assert rows[0].recorded_at == START


def test_pause_gap_is_not_counted_in_distance_or_time(client):
    before = track(3)
    after = track(3, lat=37.50, segment=1, start=START + timedelta(hours=1))
    walk = save(client, points=before + after)
    only_first = save(client, points=before)
    only_second = save(client, points=after)
    assert walk["distance_m"] == pytest.approx(only_first["distance_m"] + only_second["distance_m"], abs=0.2)
    assert walk["duration_sec"] == 80
    assert len(walk["route"]) == 2


def test_duplicate_coordinates_are_removed_from_a_recording(client):
    points = track(3)
    points.insert(1, dict(points[0]))
    points.insert(1, dict(points[0]))
    assert save(client, points=points)["point_count"] == 3


def test_impossible_jump_splits_the_route_and_is_not_counted(client):
    points = track(3)
    points.append({"latitude": 35.1, "longitude": 129.0, "recorded_at": (START + timedelta(seconds=60)).isoformat(), "segment": 0})
    points.append({"latitude": 35.1003, "longitude": 129.0, "recorded_at": (START + timedelta(seconds=80)).isoformat(), "segment": 0})
    walk = save(client, points=points)
    assert len(walk["route"]) == 2
    assert walk["distance_m"] < 200


def test_small_moves_with_coarse_timestamps_are_not_split():
    """같은 초에 여러 지점을 찍는 기기에서 몇 미터 이동을 순간 이동으로 오판하지 않는다."""
    t = START
    points = [
        GpxPoint(0, 37.5, 127.0, None, t),
        GpxPoint(0, 37.50009, 127.0, None, t),
        GpxPoint(0, 37.50018, 127.0, None, t + timedelta(milliseconds=50)),
        GpxPoint(0, 37.6, 127.0, None, t + timedelta(milliseconds=50)),
        GpxPoint(0, 37.6002, 127.0, None, t + timedelta(seconds=2)),
        GpxPoint(0, 37.6040, 127.0, None, t + timedelta(seconds=4)),
    ]
    split, jumps = split_impossible_jumps(points)
    # 10m 이동은 그대로, 같은 시각에 5km를 넘는 11km와 2초에 420m는 나눈다.
    assert jumps == 2
    assert [p.segment for p in split] == [0, 0, 0, 1, 1, 2]


def test_retrying_with_the_same_client_id_does_not_save_twice(client):
    body = {"title": "재시도", "points": track(), "client_id": "rec-12345678"}
    first = client.post("/api/my-walks", json=body)
    second = client.post("/api/my-walks", json=body)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(client.get("/api/my-walks").json()) == 1


@pytest.mark.parametrize(
    "points",
    [
        [],
        track(1),
        [{"latitude": 91, "longitude": 1}, {"latitude": 1, "longitude": 1}],
        [{"latitude": 1, "longitude": 181}, {"latitude": 1, "longitude": 1}],
    ],
)
def test_invalid_points_are_rejected(client, points):
    assert client.post("/api/my-walks", json={"title": "잘못", "points": points}).status_code == 422


def test_blank_title_and_unknown_pet_are_rejected(client):
    assert client.post("/api/my-walks", json={"title": "", "points": track()}).status_code == 422
    assert client.post("/api/my-walks", json={"title": "x", "pet_id": 9999, "points": track()}).status_code == 404


def test_oversized_request_is_refused(client):
    response = client.post("/api/my-walks", content=b"{}", headers={"Content-Type": "application/json", "Content-Length": str(MAX_REQUEST_BYTES + 1)})
    assert response.status_code == 413


# ---------- 목록, 수정, 삭제
def test_list_can_sort_and_filter(client):
    pet_id = dubu_id(client)
    short = save(client, title="짧은 길", points=track(2), pet_id=pet_id)
    long = save(client, title="긴 길", points=track(9, start=START - timedelta(days=1)), visibility="link")
    assert [w["id"] for w in client.get("/api/my-walks").json()] == [short["id"], long["id"]]
    assert [w["id"] for w in client.get("/api/my-walks", params={"sort": "distance"}).json()] == [long["id"], short["id"]]
    assert [w["id"] for w in client.get("/api/my-walks", params={"pet_id": pet_id}).json()] == [short["id"]]
    assert [w["id"] for w in client.get("/api/my-walks", params={"visibility": "link"}).json()] == [long["id"]]
    assert client.get("/api/my-walks", params={"visibility": "secret"}).status_code == 422


def test_list_items_carry_a_small_preview_instead_of_every_point(client):
    save(client, points=track(500, step=0.00001))
    item = client.get("/api/my-walks").json()[0]
    assert "route" not in item
    assert 2 <= sum(len(part) for part in item["preview"]) <= 90


def test_update_changes_only_what_was_sent(client):
    walk = save(client, memo="처음")
    updated = client.patch(f"/api/my-walks/{walk['id']}", json={"title": "새 이름"}).json()
    assert updated["title"] == "새 이름"
    assert updated["memo"] == "처음"
    assert client.patch(f"/api/my-walks/{walk['id']}", json={"memo": "수정"}).json()["memo"] == "수정"
    assert client.patch(f"/api/my-walks/{walk['id']}", json={"pet_id": 9999}).status_code == 404


@pytest.mark.parametrize("field", ["title", "memo", "visibility", "share_memo"])
def test_required_fields_cannot_be_cleared(client, field):
    walk = save(client)
    assert client.patch(f"/api/my-walks/{walk['id']}", json={field: None}).status_code == 422
    assert client.get(f"/api/my-walks/{walk['id']}").json()["title"] == "저녁 산책"


def test_pet_link_can_be_cleared(client):
    walk = save(client, pet_id=dubu_id(client))
    assert client.patch(f"/api/my-walks/{walk['id']}", json={"pet_id": None}).json()["pet_id"] is None


def test_delete_removes_the_walk_and_its_points(client):
    walk = save(client)
    assert client.delete(f"/api/my-walks/{walk['id']}").status_code == 204
    assert client.get(f"/api/my-walks/{walk['id']}").status_code == 404
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SavedWalkPoint).where(SavedWalkPoint.walk_id == walk["id"])) == 0


def test_new_tables_are_added_to_an_old_database_without_touching_others(client):
    pet_id = dubu_id(client)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE saved_walk_points"))
        connection.execute(text("DROP TABLE saved_walks"))
    assert not inspect(engine).has_table("saved_walks")
    ensure_schema(engine)
    assert inspect(engine).has_table("saved_walks") and inspect(engine).has_table("saved_walk_points")
    assert client.get(f"/api/pets/{pet_id}").status_code == 200
    assert save(client)["id"] == 1


# ---------- GPX 가져오기
def test_preview_validates_without_saving(client):
    response = preview(client)
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "가져온 길"
    assert body["version"] == "1.1"
    assert body["point_count"] == 3
    assert body["duration_sec"] == 120
    assert body["distance_m"] > 200
    assert body["has_timestamps"] is True
    assert body["duplicate_of"] is None
    assert client.get("/api/my-walks").json() == []


@pytest.mark.parametrize(
    "data, message",
    [(b"", "빈 파일"), (b"<html></html>", "GPX 파일이 아니에요"), (gpx(""), "좌표가 없어요"), (b"broken<", "형식")],
)
def test_wrong_gpx_files_get_a_readable_error(client, data, message):
    response = preview(client, data)
    assert response.status_code == 422
    assert message in response.json()["detail"]


def test_xxe_upload_is_refused_through_the_api(client):
    response = preview(client, b'<!DOCTYPE gpx [<!ENTITY x SYSTEM "file:///etc/passwd">]><gpx version="1.1"><trk><name>&x;</name></trk></gpx>')
    assert response.status_code == 422
    assert "root:" not in response.text


def test_too_large_upload_is_refused(client, monkeypatch):
    monkeypatch.setattr(api_module, "MAX_GPX_BYTES", 100)
    assert preview(client, b"x" * 200).status_code == 413


def test_gpx_without_time_is_saved_without_duration(client):
    data = gpx('<trk><trkseg><trkpt lat="37.5" lon="127"/><trkpt lat="37.51" lon="127"/></trkseg></trk>')
    body = preview(client, data).json()
    assert body["has_timestamps"] is False
    assert body["duration_sec"] is None
    assert any("시각 정보가 없어" in warning for warning in body["warnings"])
    walk = imported(client, data)
    assert walk["has_timestamps"] is False
    assert walk["duration_sec"] is None
    assert walk["average_speed_mps"] is None
    assert walk["distance_m"] > 1000
    assert datetime.fromisoformat(walk["started_at"]).year >= 2026


def test_multiple_tracks_are_kept_as_separate_parts(client):
    data = gpx(
        """<trk><trkseg><trkpt lat="37.5" lon="127"/><trkpt lat="37.501" lon="127"/></trkseg></trk>
           <trk><trkseg><trkpt lat="37.6" lon="127"/><trkpt lat="37.601" lon="127"/></trkseg></trk>"""
    )
    body = preview(client, data).json()
    assert body["track_count"] == 2
    assert body["segment_count"] == 2
    # 트랙 사이 거리는 세지 않는다.
    assert body["distance_m"] < 300
    assert len(imported(client, data)["route"]) == 2


def test_out_of_order_times_keep_the_file_order(client):
    data = gpx(
        """<trk><trkseg><trkpt lat="37.5" lon="127"><time>2026-10-30T01:05:00Z</time></trkpt>
        <trkpt lat="37.501" lon="127"><time>2026-10-30T01:00:00Z</time></trkpt>
        <trkpt lat="37.502" lon="127"><time>2026-10-30T01:06:00Z</time></trkpt></trkseg></trk>"""
    )
    body = preview(client, data).json()
    assert any("순서" in warning for warning in body["warnings"])
    assert [point["latitude"] for point in body["points"]] == [37.5, 37.501, 37.502]


def test_importing_the_same_route_again_is_flagged_but_allowed(client):
    first = imported(client)
    again = preview(client).json()
    assert again["duplicate_of"] == {"id": first["id"], "title": "가져온 길"}
    assert imported(client)["id"] != first["id"]


def test_very_long_gpx_is_handled(client):
    count = 20_000
    points = "".join(f'<trkpt lat="{37 + i * 1e-5:.7f}" lon="127.0"><time>2026-10-30T01:00:00Z</time></trkpt>' for i in range(count))
    walk = imported(client, gpx(f"<trk><trkseg>{points}</trkseg></trk>"))
    assert walk["point_count"] == count
    assert sum(len(part) for part in client.get("/api/my-walks").json()[0]["preview"]) <= 90


# ---------- GPX 내보내기
def test_export_downloads_gpx_with_a_clean_filename(client):
    walk = save(client, title="My Walk")
    response = client.get(f"/api/my-walks/{walk['id']}/gpx")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/gpx+xml")
    assert 'filename="pawpath_my-walk_20261031.gpx"' in response.headers["content-disposition"]
    assert b'<gpx version="1.1"' in response.content


def test_export_then_import_matches_the_original_route(client):
    original = imported(client)
    exported = client.get(f"/api/my-walks/{original['id']}/gpx").content
    again = preview(client, exported).json()
    assert [[[p["latitude"], p["longitude"]] for p in again["points"]]] == original["route"]
    assert again["distance_m"] == original["distance_m"]
    assert again["duration_sec"] == original["duration_sec"]
    assert again["started_at"] == original["started_at"]
    assert again["points"][0]["altitude"] == 10
    assert again["duplicate_of"]["id"] == original["id"]


def test_paused_recording_exports_separate_segments_and_round_trips(client):
    points = track(3) + track(3, lat=37.50, segment=1, start=START + timedelta(hours=1))
    walk = save(client, points=points)
    exported = client.get(f"/api/my-walks/{walk['id']}/gpx").content
    assert exported.count(b"<trkseg>") == 2
    assert preview(client, exported).json()["distance_m"] == walk["distance_m"]


# ---------- 공유
def share(client, walk_id, **body):
    response = client.post(f"/api/my-walks/{walk_id}/share", json=body)
    assert response.status_code == 200
    return response.json()


def test_private_walk_cannot_be_reached_by_any_share_route(client):
    walk = save(client)
    assert walk["share_token"] is None
    assert client.get("/api/shared/None").status_code == 404
    assert client.get("/api/shared/").status_code in (404, 405)
    assert client.get("/api/public-walks").json() == []
    with SessionLocal() as db:
        row = db.get(SavedWalk, walk["id"])
        row.share_token = "leftover-token"
        db.commit()
    # 토큰이 남아 있어도 비공개면 열리지 않는다.
    assert client.get("/api/shared/leftover-token").status_code == 404
    assert client.get("/api/shared/leftover-token/gpx").status_code == 404


def test_share_token_is_long_and_unique(client):
    first = share(client, save(client)["id"])
    second = share(client, save(client)["id"])
    assert first["visibility"] == "link"
    assert len(first["share_token"]) >= 32
    assert first["share_token"] != second["share_token"]


def test_shared_view_removes_personal_data(client):
    pet_id = dubu_id(client)
    walk = save(client, pet_id=pet_id, memo="집 앞에서 출발", duration_sec=80)
    token = share(client, walk["id"])["share_token"]
    response = client.get(f"/api/shared/{token}")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"title", "distance_m", "duration_sec", "memo", "start", "end", "route"}
    assert body["memo"] is None
    assert body["start"] == [37.4882, 127.0647]
    assert body["end"] == walk["route"][-1][-1]
    for private in ("두부", "집 앞", "recorded_at", "accuracy", "pet", "user", "2026-10-31"):
        assert private not in response.text


def test_memo_is_shown_only_when_allowed(client):
    walk = save(client, memo="그늘이 좋아요")
    token = share(client, walk["id"], share_memo=True)["share_token"]
    assert client.get(f"/api/shared/{token}").json()["memo"] == "그늘이 좋아요"
    share(client, walk["id"], share_memo=False)
    assert client.get(f"/api/shared/{token}").json()["memo"] is None


def test_shared_gpx_has_no_times_or_altitude(client):
    walk = imported(client)
    token = share(client, walk["id"])["share_token"]
    response = client.get(f"/api/shared/{token}/gpx")
    assert response.status_code == 200
    assert b"<time>" not in response.content and b"<ele>" not in response.content
    assert b"_2026" not in response.headers["content-disposition"].encode()


def test_revoked_link_stops_working_and_a_new_share_gets_a_new_token(client):
    walk = save(client)
    token = share(client, walk["id"])["share_token"]
    assert client.get(f"/api/shared/{token}").status_code == 200
    revoked = client.delete(f"/api/my-walks/{walk['id']}/share").json()
    assert revoked["share_token"] is None
    assert revoked["visibility"] == "private"
    assert client.get(f"/api/shared/{token}").status_code == 404
    assert client.get(f"/api/shared/{token}/gpx").status_code == 404
    assert share(client, walk["id"])["share_token"] != token


def test_expired_link_is_gone_until_shared_again(client):
    walk = save(client)
    shared = share(client, walk["id"], expires_in_days=7)
    assert shared["share_expires_at"] is not None
    token = shared["share_token"]
    assert client.get(f"/api/shared/{token}").status_code == 200
    with SessionLocal() as db:
        db.get(SavedWalk, walk["id"]).share_expires_at = datetime(2020, 1, 1)
        db.commit()
    assert client.get(f"/api/shared/{token}").status_code == 410
    assert client.get(f"/api/shared/{token}/gpx").status_code == 410
    renewed = share(client, walk["id"])
    assert renewed["share_token"] != token
    assert renewed["share_expires_at"] is None
    assert client.get(f"/api/shared/{token}").status_code == 404


def test_expiry_range_is_checked(client):
    walk = save(client)
    assert client.post(f"/api/my-walks/{walk['id']}/share", json={"expires_in_days": 0}).status_code == 422
    assert client.post(f"/api/my-walks/{walk['id']}/share", json={"expires_in_days": 999}).status_code == 422


def test_making_a_shared_walk_private_kills_the_link_for_good(client):
    walk = save(client)
    token = share(client, walk["id"])["share_token"]
    assert client.patch(f"/api/my-walks/{walk['id']}", json={"visibility": "private"}).json()["share_token"] is None
    assert client.get(f"/api/shared/{token}").status_code == 404
    client.patch(f"/api/my-walks/{walk['id']}", json={"visibility": "link"})
    assert client.get(f"/api/shared/{token}").status_code == 404


def test_public_list_shows_only_public_walks_without_personal_data(client):
    pet_id = dubu_id(client)
    public = save(client, title="공개 길", visibility="public", pet_id=pet_id, memo="비밀 메모")
    save(client, title="링크 길", visibility="link")
    save(client, title="비공개 길")
    response = client.get("/api/public-walks")
    items = response.json()
    assert [item["title"] for item in items] == ["공개 길"]
    assert set(items[0]) == {"token", "title", "distance_m", "duration_sec", "preview"}
    assert "비밀 메모" not in response.text and "두부" not in response.text
    assert client.get(f"/api/shared/{public['share_token']}").status_code == 200


def test_public_walk_never_expires(client):
    walk = save(client, visibility="public")
    assert share(client, walk["id"], expires_in_days=1)["share_expires_at"] is None


def test_owner_routes_return_404_for_unknown_walks(client):
    assert client.get("/api/my-walks/999").status_code == 404
    assert client.patch("/api/my-walks/999", json={"title": "x"}).status_code == 404
    assert client.delete("/api/my-walks/999").status_code == 404
    assert client.get("/api/my-walks/999/gpx").status_code == 404
    assert client.post("/api/my-walks/999/share", json={}).status_code == 404
