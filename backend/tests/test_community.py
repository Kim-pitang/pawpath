"""산책길 커뮤니티. 공유, 탐색, 좋아요, 저장, 후기, 권한, 위치 가림을 서버 쪽에서 검증한다."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal, engine
from app.migrations import ensure_schema
from app.models import CommunityTrail, Pet, SavedWalk, SavedWalkPoint, TrailBookmark, TrailLike, TrailReview, TrailReviewPhoto, WalkHistory, WalkingCourse
from app.services import auth_service, community_service
from app.services.gpx_service import GpxPoint, parse_gpx
from app.services.saved_walk_service import haversine_m
from tests.test_api_e2e import PET_BODY, dubu_id
from tests.test_auth import JPEG, other_client, signup
from tests.test_enhancement import _old_schema_engine

BASE = datetime(2026, 10, 30, 8, 0, 0)
SECRET_MEMO = "우리집 현관 앞에서 출발"
_EXIF = b"Exif\x00\x00GPSLatitude=37.4882"
EXIF_JPEG = JPEG[:2] + b"\xff\xe1" + (len(_EXIF) + 2).to_bytes(2, "big") + _EXIF + JPEG[2:]


@pytest.fixture(autouse=True)
def reset_throttle():
    auth_service.throttle.clear()
    yield
    auth_service.throttle.clear()


def line(count=40, lat=37.55, lng=126.91, step=0.0005, altitude=None):
    """북쪽으로 곧게 걷는 경로. 지점 간격은 약 55m다."""
    return [
        {
            "latitude": lat + step * index,
            "longitude": lng,
            "altitude": None if altitude is None else altitude(index),
            "recorded_at": (BASE + timedelta(seconds=40 * index)).isoformat(),
            "accuracy": 5,
            "segment": 0,
        }
        for index in range(count)
    ]


def member(login_id="alice", name="앨리스"):
    """로그인한 다른 브라우저."""
    browser = other_client()
    signup(browser, login_id=login_id, name=name)
    return browser


def make_walk(browser, title="우리집 앞 원본 이름", points=None, **overrides):
    response = browser.post("/api/my-walks", json={"title": title, "memo": SECRET_MEMO, "points": points or line(), **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def share(browser, walk=None, **overrides):
    walk = walk or make_walk(browser)
    body = {"saved_walk_id": walk["id"], "title": "양재천 산책", "description": "그늘이 좋아요", **overrides}
    response = browser.post("/api/community/trails", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def make_pet(browser, **overrides):
    response = browser.post("/api/pets", json={**PET_BODY, **overrides})
    assert response.status_code == 201, response.text
    return response.json()


def walk_trail(browser, pet_id, trail_id, tracking_source="gps", distance_km=None):
    course_id = browser.post(f"/api/community/trails/{trail_id}/start").json()["course_id"]
    body = {"pet_id": pet_id, "course_id": course_id, "duration_min": 30, "tracking_source": tracking_source}
    if distance_km is not None:
        body["distance_km"] = distance_km
    response = browser.post("/api/walks", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# ---------- 공유
def test_sharing_reuses_the_walk_without_copying_points(client):
    alice = member()
    walk = make_walk(alice)
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(SavedWalkPoint))
    trail = share(alice, walk, features=["shade", "park"], suitable_for=["small"])
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SavedWalkPoint)) == before
    assert trail["title"] == "양재천 산책"
    assert trail["author_name"] == "앨리스"
    assert trail["visibility"] == "public"
    assert trail["region"] == "서울 마포구 망원동 일대"
    assert trail["features"] == ["park", "shade"]
    assert trail["estimated_min"] > 0
    assert trail["is_mine"] is True
    assert trail["owner"] == {"saved_walk_id": walk["id"], "hide_radius_m": 200}
    assert alice.get(f"/api/my-walks/{walk['id']}").json()["community_trail"] == {"id": trail["id"], "visibility": "public"}


def test_guest_cannot_write_even_though_the_demo_user_exists(client):
    """로그인이 필수가 아닌 서버에서도 시연 보호자로 글을 쓰지 못한다."""
    alice = member()
    trail = share(alice)
    demo_walk = make_walk(client)
    path = f"/api/community/trails/{trail['id']}"
    for method, url, body in [
        ("post", "/api/community/trails", {"saved_walk_id": demo_walk["id"], "title": "시연"}),
        ("post", "/api/community/trails/preview", {"saved_walk_id": demo_walk["id"]}),
        ("post", f"{path}/like", None),
        ("delete", f"{path}/like", None),
        ("post", f"{path}/bookmark", None),
        ("delete", f"{path}/bookmark", None),
        ("post", f"{path}/reviews", {"rating": 5, "content": "좋아요"}),
        ("patch", path, {"title": "변경"}),
        ("delete", path, None),
        ("get", "/api/community/my/trails", None),
        ("get", "/api/community/my/bookmarks", None),
        ("get", "/api/community/my/likes", None),
        ("get", "/api/community/my/reviews", None),
    ]:
        kwargs = {"json": body} if body is not None else {}
        assert getattr(client, method)(url, **kwargs).status_code == 401, url


def test_guest_can_read_public_trails(client):
    alice = member()
    trail = share(alice)
    assert client.get("/api/community/trails").json()["items"][0]["id"] == trail["id"]
    detail = client.get(f"/api/community/trails/{trail['id']}").json()
    assert detail["liked"] is False
    assert detail["is_mine"] is False
    assert detail["owner"] is None
    assert detail["my_review"] is None
    assert client.get(f"/api/community/trails/{trail['id']}/gpx").status_code == 200


def test_only_my_own_walk_can_be_shared(client):
    alice, bob = member(), member("bobby", "밥")
    walk = make_walk(alice)
    assert bob.post("/api/community/trails", json={"saved_walk_id": walk["id"], "title": "훔친 길"}).status_code == 404
    assert bob.post("/api/community/trails/preview", json={"saved_walk_id": walk["id"]}).status_code == 404


def test_only_walks_someone_actually_walked_can_be_shared(client):
    """자동 생성 경로는 아직 아무도 걷지 않았다. 직접 기록과 GPX만 공유한다."""
    alice = member()
    generated = make_walk(alice, source_type="generated")
    assert alice.post("/api/community/trails/preview", json={"saved_walk_id": generated["id"]}).status_code == 422
    response = alice.post("/api/community/trails", json={"saved_walk_id": generated["id"], "title": "걷지 않은 길"})
    assert response.status_code == 422
    assert "직접 걸은 길" in response.json()["detail"]
    assert client.get("/api/community/trails").json()["total"] == 0
    for index, source in enumerate(("recorded", "imported")):
        assert share(alice, make_walk(alice, source_type=source, points=line(lng=126.92 + index * 0.01)))["id"]
    assert client.get("/api/community/trails").json()["total"] == 2


def test_same_walk_or_same_route_cannot_be_shared_twice(client):
    alice = member()
    walk = make_walk(alice)
    share(alice, walk)
    assert alice.post("/api/community/trails", json={"saved_walk_id": walk["id"], "title": "다시"}).status_code == 409
    # 같은 GPX를 다시 가져와 만든 산책길도 같은 경로다.
    again = make_walk(alice, title="다시 가져온 길")
    response = alice.post("/api/community/trails", json={"saved_walk_id": again["id"], "title": "또"})
    assert response.status_code == 409
    assert "같은 경로" in response.json()["detail"]


def test_uniqueness_is_also_enforced_by_the_database(client):
    alice = member()
    trail = share(alice)
    with SessionLocal() as db:
        row = db.get(CommunityTrail, trail["id"])
        user_id, walk_id = row.user_id, row.saved_walk_id
        for model in (TrailLike, TrailBookmark):
            db.add_all([model(user_id=user_id, community_trail_id=trail["id"]), model(user_id=user_id, community_trail_id=trail["id"])])
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
        db.add_all([TrailReview(user_id=user_id, community_trail_id=trail["id"], rating=5, content="가"), TrailReview(user_id=user_id, community_trail_id=trail["id"], rating=4, content="나")])
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(TrailReview(user_id=user_id, community_trail_id=trail["id"], rating=9, content="범위 밖"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        duplicate = CommunityTrail(**{c.name: getattr(row, c.name) for c in CommunityTrail.__table__.columns if c.name != "id"})
        db.expunge(row)
        db.add(duplicate)
        assert duplicate.saved_walk_id == walk_id
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "가" * 81},
        {"description": "가" * 2001},
        {"visibility": "link"},
        {"features": ["나쁜태그"]},
        {"suitable_for": ["cat"]},
        {"hide_radius_m": 0},
        {"hide_radius_m": 50},
        {"region": "가" * 31},
    ],
)
def test_invalid_trail_input_is_refused(client, overrides):
    alice = member()
    walk = make_walk(alice)
    assert alice.post("/api/community/trails", json={"saved_walk_id": walk["id"], "title": "길", **overrides}).status_code == 422


# ---------- 위치 가림
def test_public_route_hides_start_and_end_everywhere(client):
    alice = member()
    points = line()
    walk = make_walk(alice, points=points)
    trail = share(alice, walk, hide_radius_m=300)
    start, end = points[0], points[-1]

    def far_enough(lat, lng):
        return min(haversine_m(lat, lng, start["latitude"], start["longitude"]), haversine_m(lat, lng, end["latitude"], end["longitude"])) >= 300

    detail = client.get(f"/api/community/trails/{trail['id']}").json()
    route = [point for segment in detail["route"] for point in segment]
    assert all(far_enough(*point) for point in route)
    assert far_enough(*detail["start"]) and far_enough(*detail["end"])
    card = client.get("/api/community/trails").json()["items"][0]
    assert all(far_enough(*point) for segment in card["preview"] for point in segment)
    parsed = parse_gpx(client.get(f"/api/community/trails/{trail['id']}/gpx").content)
    assert all(far_enough(point.latitude, point.longitude) for point in parsed.points)
    course_id = client.post(f"/api/community/trails/{trail['id']}/start").json()["course_id"]
    course = client.get(f"/api/courses/{course_id}").json()
    assert all(far_enough(*point) for point in course["route"])
    assert far_enough(course["start_lat"], course["start_lng"])
    # 공개 값은 가린 뒤의 경로로 계산한다.
    assert detail["distance_m"] < walk["distance_m"] - 500


def test_hidden_radius_and_source_details_are_not_public(client):
    alice = member()
    walk = make_walk(alice, pet_id=None, share_memo=True)
    alice.post(f"/api/my-walks/{walk['id']}/share", json={"share_memo": True})
    trail = share(alice, walk)
    bodies = [
        client.get(f"/api/community/trails/{trail['id']}").text,
        client.get("/api/community/trails").text,
        client.post("/api/community/trails/nearby", json={"latitude": 37.56, "longitude": 126.91}).text,
    ]
    token = alice.get(f"/api/my-walks/{walk['id']}").json()["share_token"]
    assert token
    for text in bodies:
        for secret in (SECRET_MEMO, walk["title"], token, "hide_radius_m\":2", "started_at", "recorded_at", "alice", "accuracy"):
            assert secret not in text


def test_gpx_download_has_no_personal_metadata(client):
    alice = member()
    walk = make_walk(alice, points=line(altitude=lambda index: 10.0 + index))
    trail = share(alice, walk, title="<공개> & 이름")
    response = client.get(f"/api/community/trails/{trail['id']}/gpx")
    assert response.headers["content-type"].startswith("application/gpx+xml")
    body = response.text
    for secret in ("<time>", "<ele>", SECRET_MEMO, walk["title"], "앨리스", "alice", "2026"):
        assert secret not in body
    assert "&lt;공개&gt; &amp; 이름" in body
    assert "2026" not in response.headers["content-disposition"]
    parsed = parse_gpx(response.content)
    assert parsed.name == "<공개> & 이름"
    assert all(point.recorded_at is None and point.altitude is None for point in parsed.points)
    first = line()[0]
    assert (first["latitude"], first["longitude"]) not in {(point.latitude, point.longitude) for point in parsed.points}


def test_walk_too_short_after_hiding_is_refused(client):
    alice = member()
    walk = make_walk(alice, points=line(count=6))
    response = alice.post("/api/community/trails", json={"saved_walk_id": walk["id"], "title": "짧은 길", "hide_radius_m": 500})
    assert response.status_code == 422
    assert "너무 짧아요" in response.json()["detail"]
    assert alice.post("/api/community/trails/preview", json={"saved_walk_id": walk["id"], "hide_radius_m": 500}).status_code == 422


def test_preview_shows_what_will_be_public_and_saves_nothing(client):
    alice = member()
    walk = make_walk(alice)
    preview = alice.post("/api/community/trails/preview", json={"saved_walk_id": walk["id"], "hide_radius_m": 100}).json()
    wider = alice.post("/api/community/trails/preview", json={"saved_walk_id": walk["id"], "hide_radius_m": 500}).json()
    assert wider["distance_m"] < preview["distance_m"]
    assert preview["hidden_m"] > 0
    assert preview["region"] == "서울 마포구 망원동 일대"
    assert preview["can_navigate"] is True
    assert client.get("/api/community/trails").json()["total"] == 0


def gpx_point(lat, lng, segment=0, altitude=None):
    return GpxPoint(segment, lat, lng, altitude)


def test_route_passing_home_again_is_also_hidden_and_split():
    """집에서 출발해 한 바퀴 돌고 집 앞을 지나 더 걸어도, 그 구간은 빠지고 선을 잇지 않는다."""
    there = [gpx_point(37.5 + 0.0005 * i, 127.0) for i in range(20)]
    back = list(reversed(there))
    onward = [gpx_point(37.5, 127.0 + 0.0005 * i) for i in range(1, 20)]
    kept = community_service.public_points(there + back + onward, 200)
    home = there[0]
    assert all(haversine_m(p.latitude, p.longitude, home.latitude, home.longitude) >= 200 for p in kept)
    assert len({p.segment for p in kept}) == 2


def test_long_line_through_the_hidden_area_is_not_drawn():
    """지점이 드문 GPX에서 두 지점은 반경 밖이어도 그 사이 선이 집 위를 지나면 잇지 않는다."""
    points = [
        gpx_point(37.5, 127.0),
        gpx_point(37.51, 127.0),
        gpx_point(37.512, 127.0),
        gpx_point(37.5, 126.99),
        gpx_point(37.5, 127.01),
        gpx_point(37.5, 127.012),
        gpx_point(37.52, 127.0),
    ]
    kept = community_service.public_points(points, 200)
    starts = {p.segment: p for p in reversed(kept)}
    assert len(starts) >= 2
    # 어떤 구간의 선도 출발점 반경 안을 지나지 않는다.
    origin = 37.5
    from app.services import environment_service as env

    home = env.to_xy(37.5, 127.0, origin)
    for a, b in zip(kept, kept[1:]):
        if a.segment == b.segment:
            assert env.point_segment_m(home, env.to_xy(a.latitude, a.longitude, origin), env.to_xy(b.latitude, b.longitude, origin)) >= 200


def test_a_lone_point_between_hidden_parts_is_dropped():
    points = [gpx_point(37.5, 127.0), gpx_point(37.5, 127.01, segment=1), gpx_point(37.51, 127.0, segment=2), gpx_point(37.511, 127.0, segment=2), gpx_point(37.52, 127.0, segment=3)]
    kept = community_service.public_points(points, 100)
    assert [(p.latitude, p.longitude) for p in kept] == [(37.51, 127.0), (37.511, 127.0)]


def test_elevation_and_difficulty_come_from_the_public_route(client):
    alice = member()
    flat = share(alice, make_walk(alice, points=line(count=20)), title="평지")
    assert flat["elevation_gain_m"] is None
    assert flat["difficulty"] == "easy"
    hilly = share(alice, make_walk(alice, points=line(count=20, lng=126.92, altitude=lambda i: 10.0 + i * 8)), title="오르막")
    assert hilly["elevation_gain_m"] > 30
    assert hilly["difficulty"] in ("moderate", "hard")
    long_walk = share(alice, make_walk(alice, points=line(count=130, lng=126.93)), title="먼 길")
    assert long_walk["difficulty"] == "hard"
    # GPS 고도의 작은 흔들림은 오르막으로 세지 않는다.
    assert community_service.elevation_gain_m([gpx_point(37.5, 127, altitude=10 + (i % 2)) for i in range(50)]) == 0
    assert community_service.elevation_gain_m([gpx_point(37.5, 127, altitude=10 if i == 0 else None) for i in range(50)]) is None


# ---------- 수정, 공개 상태, 해제
def test_only_the_owner_can_edit_or_unshare(client):
    alice, bob = member(), member("bobby", "밥")
    trail = share(alice)
    path = f"/api/community/trails/{trail['id']}"
    assert bob.patch(path, json={"title": "빼앗은 제목"}).status_code == 403
    assert bob.delete(path).status_code == 403
    assert client.get(path).json()["title"] == "양재천 산책"

    updated = alice.patch(path, json={"title": "새 제목", "features": ["quiet", "quiet"], "region": "서울 어딘가"}).json()
    assert updated["title"] == "새 제목"
    assert updated["features"] == ["quiet"]
    assert updated["region"] == "서울 어딘가"
    assert alice.patch(path, json={"title": None}).status_code == 422


def test_changing_the_hidden_radius_recalculates_public_values(client):
    alice = member()
    trail = share(alice, hide_radius_m=100)
    course_id = client.post(f"/api/community/trails/{trail['id']}/start").json()["course_id"]
    before = client.get(f"/api/courses/{course_id}").json()
    updated = alice.patch(f"/api/community/trails/{trail['id']}", json={"hide_radius_m": 500}).json()
    assert updated["distance_m"] < trail["distance_m"]
    assert updated["owner"]["hide_radius_m"] == 500
    after = client.get(f"/api/courses/{course_id}").json()
    assert after["distance_km"] < before["distance_km"]
    assert after["start_lat"] > before["start_lat"]


def test_private_trail_is_closed_to_everyone_but_the_owner(client):
    alice, bob = member(), member("bobby", "밥")
    walk = make_walk(alice)
    alice.post(f"/api/my-walks/{walk['id']}/photos", content=JPEG)
    photo = alice.get(f"/api/my-walks/{walk['id']}").json()["photos"][0]["id"]
    trail = share(alice, walk, cover_photo_id=photo)
    path = f"/api/community/trails/{trail['id']}"
    course_id = bob.post(f"{path}/start").json()["course_id"]
    assert bob.post(f"{path}/bookmark").status_code == 200
    assert bob.post(f"{path}/like").status_code == 200
    review = bob.post(f"{path}/reviews", json={"rating": 5, "content": "좋아요"}).json()
    bob.post(f"/api/community/reviews/{review['id']}/photos", content=JPEG)

    assert alice.patch(path, json={"visibility": "private"}).json()["visibility"] == "private"
    for browser in (client, bob):
        assert browser.get("/api/community/trails").json()["total"] == 0
        assert browser.post("/api/community/trails/nearby", json={"latitude": 37.56, "longitude": 126.91}).json() == []
        assert browser.get("/api/community/regions").json() == []
        for url in (path, f"{path}/gpx", f"{path}/cover", f"{path}/reviews", f"/api/courses/{course_id}"):
            assert browser.get(url).status_code == 404, url
        assert browser.post(f"{path}/start").status_code == 404
        assert browser.post(f"{path}/view").status_code == 404
    assert client.get(f"/api/community/reviews/{review['id']}/photos/1").status_code == 404
    for call in (bob.post(f"{path}/like"), bob.post(f"{path}/bookmark"), bob.post(f"{path}/reviews", json={"rating": 1, "content": "나쁨"})):
        assert call.status_code == 404
    # 비공개여도 다른 사람의 수정 요청이 존재를 알려 주지 않는다.
    assert bob.patch(path, json={"title": "해킹"}).status_code == 404

    # 주인은 그대로 본다.
    assert alice.get(path).status_code == 200
    assert alice.get(f"{path}/gpx").status_code == 200
    assert alice.get(f"{path}/cover").status_code == 200
    assert alice.get(f"/api/courses/{course_id}").status_code == 200
    assert alice.get("/api/community/my/trails").json()["items"][0]["visibility"] == "private"
    assert alice.get("/api/community/my/trails").json()["items"][0]["like_count"] == 1

    # 저장한 사람의 목록에서는 숨기고 몇 개 가려졌는지만 알린다. 내 후기는 고치거나 지울 수 있고 길 이름은 숨긴다.
    saved = bob.get("/api/community/my/bookmarks").json()
    assert saved["items"] == [] and saved["hidden_count"] == 1
    assert bob.get("/api/community/my/likes").json()["hidden_count"] == 1
    mine = bob.get("/api/community/my/reviews").json()["items"][0]
    assert mine["trail_available"] is False and mine["trail_title"] is None
    assert bob.get(f"/api/community/reviews/{review['id']}/photos/{mine['photos'][0]['id']}").status_code == 200

    # 다시 공개하면 좋아요와 저장, 후기가 돌아온다.
    alice.patch(path, json={"visibility": "public"})
    back = client.get(path).json()
    assert (back["like_count"], back["bookmark_count"], back["review_count"]) == (1, 1, 1)
    assert bob.get("/api/community/my/bookmarks").json()["hidden_count"] == 0
    assert client.get(f"/api/courses/{course_id}").status_code == 200


def test_trail_can_start_private(client):
    alice = member()
    trail = share(alice, visibility="private")
    assert client.get(f"/api/community/trails/{trail['id']}").status_code == 404
    assert client.get("/api/community/trails").json()["total"] == 0


def test_missing_trail_is_404(client):
    alice = member()
    path = "/api/community/trails/99999"
    for call in (client.get(path), client.get(f"{path}/gpx"), client.get(f"{path}/reviews"), alice.post(f"{path}/like"), alice.post(f"{path}/bookmark"), alice.post(f"{path}/start"), alice.patch(path, json={"title": "x"}), alice.delete(path)):
        assert call.status_code == 404
    assert alice.patch("/api/community/reviews/99999", json={"rating": 1}).status_code == 404


def test_unsharing_removes_reactions_but_keeps_the_walk(client):
    alice, bob = member(), member("bobby", "밥")
    walk = make_walk(alice)
    trail = share(alice, walk)
    path = f"/api/community/trails/{trail['id']}"
    bob.post(f"{path}/like")
    bob.post(f"{path}/bookmark")
    review = bob.post(f"{path}/reviews", json={"rating": 4, "content": "좋아요"}).json()
    bob.post(f"/api/community/reviews/{review['id']}/photos", content=JPEG)

    assert alice.delete(path).status_code == 204
    assert client.get(path).status_code == 404
    kept = alice.get(f"/api/my-walks/{walk['id']}").json()
    assert kept["title"] == walk["title"] and kept["community_trail"] is None
    with SessionLocal() as db:
        for model in (TrailLike, TrailBookmark, TrailReview, TrailReviewPhoto):
            assert db.scalar(select(func.count()).select_from(model)) == 0
    assert bob.get("/api/community/my/bookmarks").json()["items"] == []
    # 해제한 뒤 다시 공유할 수 있다.
    assert share(alice, walk)["like_count"] == 0


def test_deleting_the_source_walk_removes_the_trail_and_its_reactions(client):
    alice, bob = member(), member("bobby", "밥")
    walk = make_walk(alice)
    trail = share(alice, walk)
    path = f"/api/community/trails/{trail['id']}"
    bob.post(f"{path}/like")
    bob.post(f"{path}/bookmark")
    bob.post(f"{path}/reviews", json={"rating": 4, "content": "좋아요"})

    assert alice.delete(f"/api/my-walks/{walk['id']}").status_code == 204
    assert client.get(path).status_code == 404
    assert client.get("/api/community/trails").json()["total"] == 0
    with SessionLocal() as db:
        for model in (CommunityTrail, TrailLike, TrailBookmark, TrailReview):
            assert db.scalar(select(func.count()).select_from(model)) == 0
    assert bob.get("/api/community/my/reviews").json()["items"] == []


# ---------- 좋아요와 저장
def test_like_toggles_and_never_counts_twice(client):
    alice, bob = member(), member("bobby", "밥")
    trail = share(alice)
    path = f"/api/community/trails/{trail['id']}"
    assert bob.post(f"{path}/like").json() == {"liked": True, "like_count": 1}
    assert bob.post(f"{path}/like").json() == {"liked": True, "like_count": 1}
    assert alice.post(f"{path}/like").json() == {"liked": True, "like_count": 2}
    assert bob.get(path).json()["liked"] is True
    assert client.get(path).json()["liked"] is False
    assert client.get(path).json()["like_count"] == 2
    assert bob.delete(f"{path}/like").json() == {"liked": False, "like_count": 1}
    assert bob.delete(f"{path}/like").json() == {"liked": False, "like_count": 1}


def test_bookmarks_are_separate_for_each_user(client):
    alice, bob, carol = member(), member("bobby", "밥"), member("carol", "캐럴")
    first = share(alice)
    second = share(alice, make_walk(alice, points=line(lng=126.92)), title="둘째 길")
    assert bob.post(f"/api/community/trails/{first['id']}/bookmark").json() == {"bookmarked": True, "bookmark_count": 1}
    assert bob.post(f"/api/community/trails/{first['id']}/bookmark").json() == {"bookmarked": True, "bookmark_count": 1}
    carol.post(f"/api/community/trails/{second['id']}/bookmark")
    carol.post(f"/api/community/trails/{second['id']}/like")

    assert [item["id"] for item in bob.get("/api/community/my/bookmarks").json()["items"]] == [first["id"]]
    assert [item["id"] for item in carol.get("/api/community/my/bookmarks").json()["items"]] == [second["id"]]
    assert carol.get("/api/community/my/likes").json()["items"][0]["liked"] is True
    assert bob.get("/api/community/my/likes").json()["items"] == []
    assert bob.delete(f"/api/community/trails/{first['id']}/bookmark").json() == {"bookmarked": False, "bookmark_count": 0}
    assert bob.get("/api/community/my/bookmarks").json()["items"] == []


# ---------- 후기
def test_review_create_edit_delete_and_average(client):
    alice, bob, carol = member(), member("bobby", "밥"), member("carol", "캐럴")
    trail = share(alice)
    path = f"/api/community/trails/{trail['id']}"
    first = bob.post(f"{path}/reviews", json={"rating": 5, "content": "  최고예요  "})
    assert first.status_code == 201
    review = first.json()
    assert review["content"] == "최고예요"
    assert review["author_name"] == "밥"
    assert review["is_mine"] is True
    assert review["verified"] is False
    assert review["edited"] is False
    carol.post(f"{path}/reviews", json={"rating": 2, "content": "그저 그래요"})

    detail = client.get(path).json()
    assert detail["review_count"] == 2 and detail["average_rating"] == 3.5
    assert bob.get(path).json()["my_review"]["id"] == review["id"]

    # 서비스 시각은 분 단위라, 수정 여부를 가리도록 작성 시각을 앞당긴다.
    with SessionLocal() as db:
        row = db.get(TrailReview, review["id"])
        row.created_at -= timedelta(minutes=5)
        db.commit()
    updated = bob.patch(f"/api/community/reviews/{review['id']}", json={"rating": 3}).json()
    assert updated["rating"] == 3 and updated["content"] == "최고예요" and updated["edited"] is True
    assert client.get(path).json()["average_rating"] == 2.5

    listed = client.get(f"{path}/reviews").json()
    assert [item["author_name"] for item in listed["items"]] == ["캐럴", "밥"]
    assert all(item["is_mine"] is False for item in listed["items"])

    assert bob.delete(f"/api/community/reviews/{review['id']}").status_code == 204
    detail = client.get(path).json()
    assert detail["review_count"] == 1 and detail["average_rating"] == 2.0
    assert carol.get("/api/community/my/reviews").json()["items"][0]["trail_title"] == "양재천 산책"


def test_review_rules(client):
    alice, bob, carol = member(), member("bobby", "밥"), member("carol", "캐럴")
    trail = share(alice)
    path = f"/api/community/trails/{trail['id']}/reviews"
    assert alice.post(path, json={"rating": 5, "content": "내 길 최고"}).status_code == 403
    review = bob.post(path, json={"rating": 5, "content": "좋아요"}).json()
    assert bob.post(path, json={"rating": 1, "content": "두 번째"}).status_code == 409
    for body in ({"rating": 0, "content": "x"}, {"rating": 6, "content": "x"}, {"rating": 5, "content": "   "}, {"rating": 5, "content": "가" * 1001}, {"content": "별점 없음"}):
        assert carol.post(path, json=body).status_code == 422
    # 다른 사람의 후기는 고치거나 지울 수 없다.
    other = f"/api/community/reviews/{review['id']}"
    assert carol.patch(other, json={"content": "바꿈"}).status_code == 403
    assert carol.delete(other).status_code == 403
    assert alice.delete(other).status_code == 403
    assert client.patch(other, json={"content": "바꿈"}).status_code == 401
    assert client.delete(other).status_code == 401
    assert bob.patch(other, json={"content": None}).status_code == 422
    assert client.get(path).json()["items"][0]["content"] == "좋아요"


@pytest.mark.parametrize(
    ("source", "distance_share", "expected"),
    [
        ("gps", None, True),
        ("gps", 0.8, True),
        ("gps", 0.2, False),
        ("simulation", None, False),
        ("manual", None, False),
    ],
)
def test_only_a_real_gps_walk_verifies_a_review(client, source, distance_share, expected):
    alice, bob = member(), member("bobby", "밥")
    trail = share(alice)
    path = f"/api/community/trails/{trail['id']}"
    review = bob.post(f"{path}/reviews", json={"rating": 5, "content": "좋아요"}).json()
    assert review["verified"] is False
    pet = make_pet(bob)
    course_km = bob.get(f"/api/courses/{bob.post(f'{path}/start').json()['course_id']}").json()["distance_km"]
    distance = None if distance_share is None else round(course_km * distance_share, 2)
    walk_trail(bob, pet["id"], trail["id"], source, distance)
    assert client.get(f"{path}/reviews").json()["items"][0]["verified"] is expected
    assert bob.get(path).json()["walked"] is expected
    assert client.get(path).json()["walked"] is False


def test_verification_follows_the_walk_record(client):
    alice, bob = member(), member("bobby", "밥")
    trail = share(alice)
    path = f"/api/community/trails/{trail['id']}"
    bob.post(f"{path}/reviews", json={"rating": 5, "content": "좋아요"})
    walk = walk_trail(bob, make_pet(bob)["id"], trail["id"])
    assert walk["community_trail_id"] == trail["id"]
    assert client.get(f"{path}/reviews").json()["items"][0]["verified"] is True
    assert bob.delete(f"/api/walks/{walk['id']}").status_code == 204
    assert client.get(f"{path}/reviews").json()["items"][0]["verified"] is False


def test_review_photos_are_cleaned_and_limited(client):
    alice, bob, carol = member(), member("bobby", "밥"), member("carol", "캐럴")
    trail = share(alice)
    review = bob.post(f"/api/community/trails/{trail['id']}/reviews", json={"rating": 5, "content": "사진 후기"}).json()
    url = f"/api/community/reviews/{review['id']}/photos"
    assert carol.post(url, content=JPEG).status_code == 403
    assert client.post(url, content=JPEG).status_code == 401
    assert bob.post(url, content=b"<script>alert(1)</script>").status_code == 422
    assert bob.post(url, content=b"").status_code == 422
    photo = bob.post(url, content=EXIF_JPEG)
    assert photo.status_code == 201
    shown = client.get(f"{url}/{photo.json()['id']}")
    assert shown.status_code == 200
    assert shown.headers["content-type"] == "image/jpeg"
    assert shown.headers["x-content-type-options"] == "nosniff"
    assert b"GPSLatitude" not in shown.content
    assert bob.post(url, content=JPEG).status_code == 201
    assert bob.post(url, content=JPEG).status_code == 201
    assert bob.post(url, content=JPEG).status_code == 409
    assert len(client.get(f"/api/community/trails/{trail['id']}/reviews").json()["items"][0]["photos"]) == 3
    assert carol.delete(f"{url}/{photo.json()['id']}").status_code == 403
    assert bob.delete(f"{url}/{photo.json()['id']}").status_code == 204
    assert client.get(f"{url}/{photo.json()['id']}").status_code == 404


def test_oversized_review_photo_is_refused(client):
    alice, bob = member(), member("bobby", "밥")
    review = bob.post(f"/api/community/trails/{share(alice)['id']}/reviews", json={"rating": 5, "content": "큰 사진"}).json()
    response = bob.post(f"/api/community/reviews/{review['id']}/photos", content=JPEG + b"\0" * (5 * 1024 * 1024))
    assert response.status_code == 413


# ---------- 대표 이미지
def test_only_the_chosen_cover_photo_becomes_public(client):
    alice, bob = member(), member("bobby", "밥")
    walk = make_walk(alice)
    alice.post(f"/api/my-walks/{walk['id']}/photos", content=EXIF_JPEG)
    alice.post(f"/api/my-walks/{walk['id']}/photos", content=JPEG)
    photos = alice.get(f"/api/my-walks/{walk['id']}").json()["photos"]
    trail = share(alice, walk, cover_photo_id=photos[0]["id"])
    path = f"/api/community/trails/{trail['id']}"
    shown = client.get(f"{path}/cover")
    assert shown.status_code == 200
    assert b"GPSLatitude" not in shown.content
    # 원본 사진 주소는 여전히 주인만 열 수 있다.
    assert bob.get(f"/api/my-walks/{walk['id']}/photos/{photos[1]['id']}").status_code == 404

    # 대표 이미지를 지우면 비워지고 다른 사진으로 저절로 바뀌지 않는다.
    assert alice.delete(f"/api/my-walks/{walk['id']}/photos/{photos[0]['id']}").status_code == 204
    assert client.get(path).json()["cover_photo_id"] is None
    assert client.get(f"{path}/cover").status_code == 404


def test_cover_must_belong_to_the_walk(client):
    alice = member()
    other = make_walk(alice, points=line(lng=126.92))
    alice.post(f"/api/my-walks/{other['id']}/photos", content=JPEG)
    photo = alice.get(f"/api/my-walks/{other['id']}").json()["photos"][0]["id"]
    walk = make_walk(alice)
    assert alice.post("/api/community/trails", json={"saved_walk_id": walk["id"], "title": "길", "cover_photo_id": photo}).status_code == 422
    trail = share(alice, walk)
    assert alice.patch(f"/api/community/trails/{trail['id']}", json={"cover_photo_id": photo}).status_code == 422
    assert alice.patch(f"/api/community/trails/{trail['id']}", json={"cover_photo_id": None}).status_code == 200


# ---------- 탐색
@pytest.fixture
def catalog(client):
    alice, bob = member(), member("bobby", "밥")
    short = share(alice, make_walk(alice, points=line(count=20)), title="짧은 공원길", features=["park"], suitable_for=["small", "senior"], region="망원동")
    middle = share(alice, make_walk(alice, points=line(count=50, lng=126.92)), title="강변 산책", description="한강 바람", features=["waterside"], suitable_for=["medium"], region="합정동")
    long_trail = share(bob, make_walk(bob, points=line(count=120, lng=126.93)), title="긴 숲길 100%", features=["forest"], suitable_for=["active"], region="망원동")
    return {"alice": alice, "bob": bob, "short": short, "middle": middle, "long": long_trail}


def ids(client, **params):
    return [item["id"] for item in client.get("/api/community/trails", params=params).json()["items"]]


def test_search_and_filters(client, catalog):
    short, middle, long_trail = catalog["short"]["id"], catalog["middle"]["id"], catalog["long"]["id"]
    assert ids(client) == [long_trail, middle, short]
    assert ids(client, q="공원") == [short]
    assert ids(client, q="한강") == [middle]
    assert ids(client, q="망원동") == [long_trail, short]
    assert ids(client, region="합정동") == [middle]
    assert ids(client, max_km=2) == [short]
    assert ids(client, min_km=2, max_km=5) == [middle]
    assert ids(client, min_km=5) == [long_trail]
    assert ids(client, max_minutes=20) == [short]
    assert ids(client, min_minutes=60) == [long_trail]
    assert ids(client, difficulty="easy") == [short]
    assert ids(client, difficulty="hard") == [long_trail]
    assert ids(client, suitable="senior") == [short]
    assert ids(client, suitable="small", region="합정동") == []
    assert ids(client, feature="forest") == [long_trail]
    assert client.get("/api/community/regions").json() == [{"region": "망원동", "count": 2}, {"region": "합정동", "count": 1}]


@pytest.mark.parametrize("query", ["_", "' OR 1=1 --", '"; DROP TABLE community_trails; --', "\\"])
def test_search_text_is_never_treated_as_sql(client, catalog, query):
    assert ids(client, q=query) == []
    assert client.get("/api/community/trails").json()["total"] == 3


def test_percent_sign_is_searched_as_a_letter(client, catalog):
    """와일드카드로 풀리면 모든 길이 나온다. 제목에 %가 있는 길만 나와야 한다."""
    assert ids(client, q="%") == [catalog["long"]["id"]]
    assert ids(client, q="100%") == [catalog["long"]["id"]]


@pytest.mark.parametrize("params", [{"sort": "hacked"}, {"difficulty": "x"}, {"suitable": "cat"}, {"feature": "%"}, {"page": 0}, {"size": 500}, {"min_km": -1}])
def test_invalid_list_parameters_are_refused(client, params):
    assert client.get("/api/community/trails", params=params).status_code == 422


def test_sorting_by_popularity_and_rating(client, catalog):
    short, middle, long_trail = catalog["short"]["id"], catalog["middle"]["id"], catalog["long"]["id"]
    carol = member("carol", "캐럴")
    carol.post(f"/api/community/trails/{short}/like")
    catalog["bob"].post(f"/api/community/trails/{short}/bookmark")
    catalog["bob"].post(f"/api/community/trails/{middle}/like")
    assert ids(client, sort="popular") == [short, middle, long_trail]

    # 후기가 하나뿐인 5점은 후기 여럿의 높은 평균을 앞서지 않고, 후기가 없으면 뒤로 간다.
    carol.post(f"/api/community/trails/{middle}/reviews", json={"rating": 5, "content": "하나뿐인 5점"})
    for index in range(4):
        reviewer = member(f"reviewer{index}", f"평가자{index}")
        reviewer.post(f"/api/community/trails/{long_trail}/reviews", json={"rating": 5 if index else 4, "content": "좋아요"})
    assert ids(client, sort="rating") == [long_trail, middle, short]


def test_pagination(client):
    alice = member()
    created = [share(alice, make_walk(alice, points=line(count=12, lng=126.9 + index * 0.001)), title=f"길 {index}")["id"] for index in range(5)]
    first = client.get("/api/community/trails", params={"size": 2}).json()
    assert [item["id"] for item in first["items"]] == created[:-3:-1]
    assert (first["total"], first["page"], first["has_next"]) == (5, 1, True)
    last = client.get("/api/community/trails", params={"size": 2, "page": 3}).json()
    assert [item["id"] for item in last["items"]] == [created[0]]
    assert last["has_next"] is False
    assert client.get("/api/community/trails", params={"size": 2, "page": 9}).json()["items"] == []


def test_nearby_uses_the_body_and_sorts_by_distance(client):
    alice = member()
    near = share(alice, make_walk(alice, points=line(count=12)), title="가까운 길")
    far = share(alice, make_walk(alice, points=line(count=12, lat=37.58)), title="먼 길")
    share(alice, make_walk(alice, points=line(count=12, lat=35.1, lng=129.0)), title="부산 길")
    body = client.post("/api/community/trails/nearby", json={"latitude": 37.55, "longitude": 126.91, "radius_km": 10}).json()
    assert [item["id"] for item in body] == [near["id"], far["id"]]
    assert body[0]["distance_from_me_m"] < body[1]["distance_from_me_m"]
    assert [item["id"] for item in client.post("/api/community/trails/nearby", json={"latitude": 37.55, "longitude": 126.91, "radius_km": 1}).json()] == [near["id"]]
    assert client.post("/api/community/trails/nearby", json={"latitude": 91, "longitude": 0}).status_code == 422
    assert client.get("/api/community/trails/nearby").status_code in (404, 405, 422)


def test_recommendations_fit_the_pet(client):
    alice, bob = member(), member("bobby", "밥")
    # 작은 소심한 노령견: 권장 거리가 짧다.
    senior = make_pet(bob, size="small", age_years=12, weight_kg=4, activity_level="low", personality="timid", novelty_reaction="anxious")
    short = share(alice, make_walk(alice, points=line(count=18)), title="짧은 길", suitable_for=["senior"])
    far = share(alice, make_walk(alice, points=line(count=130, lng=126.92)), title="아주 긴 길", suitable_for=["active"])
    mine = share(bob, make_walk(bob, points=line(count=18, lng=126.93)), title="내 길", suitable_for=["senior"])
    response = bob.get("/api/community/trails/recommended", params={"pet_id": senior["id"]})
    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [short["id"], far["id"]]
    assert mine["id"] not in {item["id"] for item in body}
    assert body[0]["match_score"] > body[1]["match_score"]
    assert any("노령견" in reason for reason in body[0]["reasons"])
    assert any("km" in reason for reason in body[0]["reasons"])
    assert body[1]["reasons"] == []


def test_recommendations_follow_learned_taste(client):
    alice, bob = member(), member("bobby", "밥")
    pet = make_pet(bob)
    park = share(alice, make_walk(alice, points=line(count=25)), title="공원 길", features=["park"])
    river = share(alice, make_walk(alice, points=line(count=25, lng=126.92)), title="강변 길", features=["waterside"])
    with SessionLocal() as db:
        db.get(Pet, pet["id"]).learned_attribute_weights = {"river": 0.6, "park": -0.6}
        db.commit()
    assert bob.get("/api/community/trails/recommended", params={"pet_id": pet["id"]}).json()[0]["id"] == river["id"]
    with SessionLocal() as db:
        db.get(Pet, pet["id"]).learned_attribute_weights = {"river": -0.6, "park": 0.6}
        db.commit()
    assert bob.get("/api/community/trails/recommended", params={"pet_id": pet["id"]}).json()[0]["id"] == park["id"]


def test_recommendations_refuse_another_users_pet(client):
    alice, bob = member(), member("bobby", "밥")
    pet = make_pet(alice)
    assert bob.get("/api/community/trails/recommended", params={"pet_id": pet["id"]}).status_code == 404
    # 로그인하지 않으면 시연 반려동물로 볼 수 있다. 다른 보호자의 반려동물은 안 된다.
    assert client.get("/api/community/trails/recommended", params={"pet_id": pet["id"]}).status_code == 404
    assert client.get("/api/community/trails/recommended", params={"pet_id": dubu_id(client)}).status_code == 200


def test_view_count_ignores_the_owner_and_keeps_updated_at(client):
    alice, bob = member(), member("bobby", "밥")
    trail = share(alice)
    path = f"/api/community/trails/{trail['id']}"
    assert alice.post(f"{path}/view").status_code == 204
    assert client.get(path).json()["view_count"] == 0
    # 상세를 읽는 것만으로는 세지 않는다.
    assert client.get(path).json()["view_count"] == 0
    assert bob.post(f"{path}/view").status_code == 204
    assert client.post(f"{path}/view").status_code == 204
    after = client.get(path).json()
    assert after["view_count"] == 2
    assert after["updated_at"] == trail["updated_at"]


def test_text_is_returned_as_is_and_control_characters_are_removed(client):
    alice = member()
    script = "<script>alert('x')</script>"
    trail = share(alice, title=f"{script}\x00제목\x07", description=f"<img src=x onerror=alert(1)>\n둘째 줄\x1b")
    detail = client.get(f"/api/community/trails/{trail['id']}")
    assert detail.headers["content-type"].startswith("application/json")
    body = detail.json()
    assert body["title"] == f"{script}제목"
    assert body["description"] == "<img src=x onerror=alert(1)>\n둘째 줄"
    assert b"<script>" in client.get(f"/api/community/trails/{trail['id']}").content
    assert "<script>" not in client.get(f"/api/community/trails/{trail['id']}/gpx").text


# ---------- 산책 시작
def test_starting_a_trail_shares_one_course_outside_recommendations(client):
    alice, bob = member(), member("bobby", "밥")
    trail = share(alice, title="함께 걷는 길")
    path = f"/api/community/trails/{trail['id']}/start"
    course_id = bob.post(path).json()["course_id"]
    assert client.post(path).json()["course_id"] == course_id
    assert alice.post(path).json()["course_id"] == course_id
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(WalkingCourse).where(WalkingCourse.community_trail_id == trail["id"])) == 1
    course = bob.get(f"/api/courses/{course_id}").json()
    assert course["name"] == "함께 걷는 길"
    assert len(course["route"]) >= 2
    # 추천 후보와 코스 목록에는 들어가지 않는다.
    assert course_id not in {item["id"] for item in bob.get("/api/courses").json()}
    pet = make_pet(bob)
    recommendation = bob.post("/api/recommendations", json={"pet_id": pet["id"], "weather_scenario": "live"}).json()
    assert course_id not in {item["course_id"] for item in recommendation["courses"]}
    assert bob.post(f"/api/courses/{course_id}/approach", json={"latitude": 37.56, "longitude": 126.91}).status_code == 200


def test_navigation_checks_work_on_a_trail_course_in_any_region(client):
    """길 안내 화면이 부르는 날씨 재평가, 안전 지수, 주변 시설이 커뮤니티 코스에서도 동작한다."""
    alice, bob = member(), member("bobby", "밥")
    pet = make_pet(bob)
    for trail in (share(alice), share(alice, make_walk(alice, points=line(lng=126.93)), region="내가 지은 지역")):
        course_id = bob.post(f"/api/community/trails/{trail['id']}/start").json()["course_id"]
        course = bob.get(f"/api/courses/{course_id}").json()
        assert course["is_personal"] is False
        body = {"pet_id": pet["id"], "course_id": course_id, "latitude": course["start_lat"], "longitude": course["start_lng"], "progress_m": 100, "weather_scenario": "rain_now"}
        assert bob.post("/api/routes/alternative", json=body).status_code == 200
        assert bob.get("/api/safety", params={"pet_id": pet["id"], "course_id": course_id}).status_code == 200
        assert bob.get(f"/api/courses/{course_id}/nearby").status_code == 200


def test_walk_on_a_trail_goes_through_the_normal_feedback_and_report(client):
    alice, bob = member(), member("bobby", "밥")
    trail = share(alice)
    pet = make_pet(bob)
    walk = walk_trail(bob, pet["id"], trail["id"])
    feedback = bob.post("/api/feedback", json={"walk_id": walk["id"], "walk_rating": 5, "pet_rating": 5, "difficulty": "just_right", "weather_rating": 5, "would_revisit": True})
    assert feedback.status_code == 201
    assert bob.get(f"/api/pets/{pet['id']}/insights").status_code == 200
    assert bob.get("/api/walks/report", params={"pet_id": pet["id"]}).status_code == 200


def test_route_that_cannot_be_joined_is_not_navigable(client):
    alice = member()
    points = line(count=20) + [{**point, "segment": 1} for point in line(count=20, lat=37.58)]
    trail = share(alice, make_walk(alice, points=points))
    detail = client.get(f"/api/community/trails/{trail['id']}").json()
    assert detail["can_navigate"] is False
    response = client.post(f"/api/community/trails/{trail['id']}/start")
    assert response.status_code == 422
    assert "길 안내" in response.json()["detail"]


def test_unsharing_closes_the_course_but_keeps_other_users_walks(client):
    alice, bob = member(), member("bobby", "밥")
    trail = share(alice, title="개인적인 제목")
    pet = make_pet(bob)
    walk = walk_trail(bob, pet["id"], trail["id"])
    course_id = walk["course_id"]
    assert alice.delete(f"/api/community/trails/{trail['id']}").status_code == 204

    for browser in (alice, bob, client):
        assert browser.get(f"/api/courses/{course_id}").status_code == 404
    listed = bob.get("/api/walks").json()
    assert [item["id"] for item in listed] == [walk["id"]]
    assert listed[0]["course_name"] == "삭제된 커뮤니티 산책길"
    assert listed[0]["community_trail_id"] is None
    assert bob.get(f"/api/pets/{pet['id']}/insights").status_code == 200
    with SessionLocal() as db:
        course = db.get(WalkingCourse, course_id)
        assert course.route == [] and course.owner_user_id is None and course.is_active is False
        assert (course.start_lat, course.start_lng) == (0.0, 0.0)


def test_course_row_is_retired_when_the_source_walk_is_deleted(client):
    alice, bob = member(), member("bobby", "밥")
    walk = make_walk(alice)
    trail = share(alice, walk)
    pet = make_pet(bob)
    course_id = walk_trail(bob, pet["id"], trail["id"])["course_id"]
    assert alice.delete(f"/api/my-walks/{walk['id']}").status_code == 204
    assert client.get(f"/api/courses/{course_id}").status_code == 404
    assert bob.get("/api/walks").status_code == 200


def test_trail_course_is_independent_of_the_personal_course(client):
    """같은 산책길을 내 추천 후보로 등록해도 커뮤니티 코스와 섞이지 않는다."""
    alice = member()
    walk = make_walk(alice)
    trail = share(alice, walk)
    trail_course = alice.post(f"/api/community/trails/{trail['id']}/start").json()["course_id"]
    personal = alice.post(f"/api/my-walks/{walk['id']}/course").json()["course"]["id"]
    assert personal != trail_course
    assert alice.get(f"/api/my-walks/{walk['id']}").json()["course"]["id"] == personal
    assert alice.delete(f"/api/my-walks/{walk['id']}").status_code == 204
    assert alice.get(f"/api/courses/{trail_course}").status_code == 404


# ---------- DB 호환
def test_old_database_gets_the_community_column_and_tables(tmp_path):
    old = _old_schema_engine(tmp_path)
    assert "community_trail_id" not in {column["name"] for column in inspect(old).get_columns("walking_courses")}
    added = ensure_schema(old)
    assert "walking_courses.community_trail_id" in added
    inspector = inspect(old)
    indexes = {index["name"]: index["unique"] for index in inspector.get_indexes("walking_courses")}
    assert indexes.get("ix_walking_courses_community_trail_id")
    assert {"community_trails", "trail_likes", "trail_bookmarks", "trail_reviews", "trail_review_photos"} <= set(inspector.get_table_names())


def test_new_tables_declare_foreign_keys_and_indexes(client):
    inspector = inspect(engine)
    for table in ("trail_likes", "trail_bookmarks", "trail_reviews"):
        references = {fk["referred_table"]: fk["options"].get("ondelete") for fk in inspector.get_foreign_keys(table)}
        assert references["community_trails"] == "CASCADE"
        assert references["users"] == "CASCADE"
        assert {f"ix_{table}_user_id", f"ix_{table}_community_trail_id"} <= {index["name"] for index in inspector.get_indexes(table)}
