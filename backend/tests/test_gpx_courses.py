"""공개 GPX 파일을 추천 후보 코스로 적재하기."""
import json
import unicodedata
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import WalkingCourse
from app.recommender.diversity import route_overlap
from app.seed import DATA_DIR, seed_courses
from app.services import gpx_course_service as service
from app.services.recommendation_service import active_courses
from app.services.saved_walk_service import haversine_m

GPX_COURSES = DATA_DIR / "courses_gpx.json"
# 망원한강공원 GPX의 앞부분. 실제 파일과 같은 trkpt 형식이다.
MANGWON = [(37.550227, 126.901069), (37.551030, 126.900129), (37.552154, 126.898829), (37.553270, 126.897472), (37.554594, 126.895905)]


def gpx(points, name="테스트 코스", ele=None) -> bytes:
    rows = []
    for index, (lat, lng) in enumerate(points):
        child = f"<ele>{ele[index]}</ele>" if ele and ele[index] is not None else ""
        rows.append(f'<trkpt lat="{lat}" lon="{lng}">{child}</trkpt>')
    return (
        '<?xml version="1.0" encoding="utf-8"?><gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><name>{name}</name><trkseg>{''.join(rows)}</trkseg></trk></gpx>"
    ).encode()


def test_clean_points_keeps_order_and_drops_bad_points():
    raw = [
        (37.5500, 126.9000, None),
        (37.5500, 126.9000, None),  # 연속 중복
        (0.0, 0.0, None),  # 위치를 못 잡은 기기
        (35.0, 140.0, None),  # 국내 범위 밖
        (37.5510, 126.9000, None),
        (37.5600, 126.9000, None),  # 혼자 1km 튄 지점
        (37.5511, 126.9001, None),
        (37.5520, 126.9000, None),
    ]
    points, altitudes, report = service.clean_points(raw)
    assert points == [[37.55, 126.9], [37.551, 126.9], [37.5511, 126.9001], [37.552, 126.9]]
    assert len(altitudes) == len(points)
    assert (report.duplicates, report.invalid_coordinates, report.outside_korea, report.spikes) == (1, 1, 1, 1)


def test_distance_is_haversine_sum_and_one_way_becomes_out_and_back():
    result = service.analyze("마포구_테스트.gpx", gpx(MANGWON))
    assert result.status == "ok"
    expected = sum(haversine_m(*a, *b) for a, b in zip(MANGWON, MANGWON[1:])) / 1000
    assert result.one_way_km == pytest.approx(expected, abs=0.001)
    assert result.route_type == "one_way"

    route = service.course_route(result)
    assert route[0] == route[-1] == list(MANGWON[0])
    assert route[len(MANGWON) - 1] == list(MANGWON[-1])
    values = service.build_values(result)
    assert values["distance_km"] == pytest.approx(round(expected * 2, 2))
    assert values["data_sources"]["gpx"]["one_way_km"] == round(expected, 2)
    assert values["data_sources"]["gpx"]["end"] == list(MANGWON[-1])
    assert "distance_km(왕복=편도×2)" in values["data_sources"]["gpx"]["estimated"]


def test_circular_route_is_kept_as_is():
    loop = [*MANGWON, (37.5520, 126.9030), (37.5503, 126.9012)]
    result = service.analyze("loop.gpx", gpx(loop))
    assert result.route_type == "circular"
    assert service.course_route(result) == [list(p) for p in loop]


def test_missing_elevation_stays_unknown():
    result = service.analyze("마포구_테스트.gpx", gpx(MANGWON))
    assert result.elevation is None
    values = service.build_values(result)
    assert values["data_sources"]["gpx"]["elevation"] is None
    assert values["difficulty"] == "easy"  # 엔진 입력은 기존 내 산책길 코스와 같은 중립값
    assert {"difficulty", "crowd_level", "pet_allowed"} <= set(values["data_sources"]["unknown"])
    assert "elevation" not in values["data_sources"]["gpx"]["measured"]


def test_elevation_gain_sets_difficulty():
    result = service.analyze("hill.gpx", gpx(MANGWON, ele=[10, 30, 50, 45, 80]))
    assert result.elevation["gain_m"] == 75 and result.elevation["loss_m"] == 5
    values = service.build_values(result)
    assert values["difficulty"] == "hard"
    assert "difficulty" not in values["data_sources"]["unknown"]


@pytest.mark.parametrize(
    "data, message",
    [
        (b"<gpx", "형식"),
        (gpx([(37.55, 126.90)]), "2개"),
        (gpx([(37.55, 126.90), (37.58, 126.90)]), "끊긴 경로"),
        (gpx([(37.55, 126.90), (37.5502, 126.90)]), "100m"),
    ],
)
def test_invalid_files_are_reported(data, message):
    result = service.analyze("bad.gpx", data)
    assert result.status == "error" and message in result.error


def test_code_is_same_for_nfc_and_nfd_file_names():
    nfc = "강남구_양재천.gpx"
    assert service.course_code(unicodedata.normalize("NFD", nfc)) == service.course_code(nfc) == "gpx-강남구_양재천"


def test_duplicates_are_detected():
    first = service.analyze("a.gpx", gpx(MANGWON))
    same_file = service.analyze("b.gpx", gpx(MANGWON))
    shifted = service.analyze("c.gpx", gpx([(lat + 0.00005, lng) for lat, lng in MANGWON]))
    other = service.analyze("d.gpx", gpx([(37.5200, 127.0500), (37.5230, 127.0500), (37.5260, 127.0510)]))
    service.find_overlaps([first, same_file, shifted, other], [])
    assert [r.status for r in (first, same_file, shifted, other)] == ["ok", "duplicate", "duplicate", "ok"]
    assert same_file.duplicate_of == "a.gpx" and shifted.duplicate_of == "gpx-a"


def test_area_follows_service_area_radius():
    inside = service.build_values(service.analyze("마포구_망원한강공원.gpx", gpx(MANGWON)))
    assert inside["area"] == "서울 마포구 망원동 일대" and inside["data_sources"]["gpx"]["in_service_area"]
    far = service.analyze("노원구_경춘선숲길.gpx", gpx([(37.6258, 127.0726), (37.6237, 127.0771), (37.6237, 127.0839)]))
    values = service.build_values(far)
    assert values["area"] == "서울 노원구 일대" and values["facilities"] == []
    assert values["data_sources"]["facilities_unavailable"]


def test_upsert_is_idempotent_and_keeps_admin_toggle(client):
    row = {"code": "gpx-마포구_테스트", **service.build_values(service.analyze("마포구_테스트.gpx", gpx(MANGWON)))}
    assert "is_active" not in row
    with SessionLocal() as db:
        before = db.scalar(select(func.count()).select_from(WalkingCourse))
        assert service.upsert(db, [row]) == (1, 0)
        assert service.upsert(db, [row]) == (0, 1)
        assert db.scalar(select(func.count()).select_from(WalkingCourse)) == before + 1
        assert any(c.code == row["code"] for c in active_courses(db, None))

        service.set_active(db, row["code"], False)
        service.upsert(db, [row])
        course = db.scalar(select(WalkingCourse).where(WalkingCourse.code == row["code"]))
        assert course.is_active is False
        assert all(c.code != row["code"] for c in active_courses(db, None))
        with pytest.raises(ValueError):
            service.set_active(db, "mangwon-hangang", False)  # 시드 코스는 이 도구로 끄지 않는다


# 아래는 저장소에 들어 있는 실제 GPX 20개 적재 결과를 확인한다.


def test_committed_gpx_courses_are_valid():
    rows = json.loads(GPX_COURSES.read_text(encoding="utf-8"))
    assert len(rows) == 20 and len({row["code"] for row in rows}) == 20
    for row in rows:
        gpx_info = row["data_sources"]["gpx"]
        assert row["code"].startswith("gpx-") and row["data_sources"]["source_type"] == "gpx_import"
        assert unicodedata.is_normalized("NFC", row["code"])
        assert "is_active" not in row
        route = row["route"]
        assert route[0] == route[-1] == [row["start_lat"], row["start_lng"]]
        assert all(33 <= lat <= 39 and 124 <= lng <= 132 for lat, lng in route)
        walked = sum(haversine_m(*a, *b) for a, b in zip(route, route[1:])) / 1000
        assert walked == pytest.approx(row["distance_km"], abs=0.01)
        assert gpx_info["route_type"] in ("circular", "one_way")
        if gpx_info["route_type"] == "one_way":
            assert row["distance_km"] == pytest.approx(gpx_info["one_way_km"] * 2, abs=0.02)
        assert gpx_info["elevation"] is None  # 받은 파일에 고도가 없다
        assert 0 < row["distance_km"] <= 10


def test_committed_gpx_courses_do_not_duplicate_seed_routes():
    rows = json.loads(GPX_COURSES.read_text(encoding="utf-8"))
    seeds = [c for name in ("courses.json", "courses_gaepo.json") for c in json.loads((DATA_DIR / name).read_text(encoding="utf-8"))]
    for row in rows:
        route = tuple(map(tuple, row["route"]))
        for seed in seeds:
            assert route_overlap(route, tuple(map(tuple, seed["route"]))) < service.SAME_ROUTE_OVERLAP


def test_seed_loads_gpx_courses_into_candidates(client):
    with SessionLocal() as db:
        gpx_courses = list(db.scalars(select(WalkingCourse).where(WalkingCourse.code.like("gpx-%"))))
        assert len(gpx_courses) == 20 and all(c.is_active for c in gpx_courses)
        seed_courses(db)  # 다시 실행해도 늘지 않는다
        db.commit()
        assert db.scalar(select(func.count()).select_from(WalkingCourse).where(WalkingCourse.code.like("gpx-%"))) == 20
        in_area = {c.code for c in active_courses(db, None) if c.code.startswith("gpx-")}
    expected = {row["code"] for row in json.loads(GPX_COURSES.read_text(encoding="utf-8")) if row["area"] == "서울 마포구 망원동 일대"}
    assert in_area == expected and in_area
    listed = {course["code"] for course in client.get("/api/courses").json()}
    assert expected <= listed
