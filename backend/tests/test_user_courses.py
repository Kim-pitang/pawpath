"""내 산책길을 추천 후보 코스로 쓰기."""
import json
from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app.config import get_settings
from app.database import Base, SessionLocal
from app.main import app
from app.migrations import ensure_schema
from app.models import WalkingCourse
from app.recommender.engine import recommend
from app.recommender.explain import non_environment_cautions
from app.recommender.features import build_features
from app.services import environment_service, user_course_service
from app.services.recommendation_service import to_course_data
from tests.conftest import EMPTY_STATE, NOW, default_schedule, make_forecast, make_pet, seed_course_data
from tests.test_api_e2e import PET_BODY, dubu_id

START = (37.5545, 126.9065)
PARK = (37.5512, 126.9034)  # 망원정마당 음수대 옆
PASSWORD = "walk-with-dubu-1"


def line(a, b, step_m=10.0):
    """두 점 사이를 약 step_m 간격으로 나눈다. GPS 기록처럼 지점이 촘촘하다."""
    distance = ((a[0] - b[0]) * 110540) ** 2 + ((a[1] - b[1]) * 88000) ** 2
    count = max(1, round(distance**0.5 / step_m))
    return [(a[0] + (b[0] - a[0]) * i / count, a[1] + (b[1] - a[1]) * i / count) for i in range(count)]


def out_and_back(far):
    return line(START, far) + line(far, START) + [START]


def points(route, segment=0, start_time=None):
    rows = []
    for index, (lat, lng) in enumerate(route):
        row = {"latitude": lat, "longitude": lng, "segment": segment, "accuracy": 6}
        if start_time:
            row["recorded_at"] = (start_time + timedelta(seconds=8 * index)).isoformat()
        rows.append(row)
    return rows


def make_walk(client, route=None, source="recorded", title="망원정마당 다녀오기", extra_points=None):
    body = {"title": title, "source_type": source, "points": points(route or out_and_back(PARK), start_time=NOW) + (extra_points or [])}
    response = client.post("/api/my-walks", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def register(client, walk_id):
    return client.post(f"/api/my-walks/{walk_id}/course")


def signup(client, login_id):
    assert client.post("/api/auth/signup", json={"login_id": login_id, "password": PASSWORD, "name": login_id}).status_code == 201


def course_of(client, course_id):
    return next((course for course in client.get("/api/courses").json() if course["id"] == course_id), None)


# ---------- 등록
def test_recorded_walk_becomes_a_familiar_course_marked_with_what_is_unknown(client):
    walk = make_walk(client)
    response = register(client, walk["id"])
    assert response.status_code == 200, response.text
    info = response.json()["course"]
    assert info["active"] is True
    assert info["area"] == "서울 마포구 망원동 일대"
    assert info["in_current_area"] is True
    assert info["environment_measured"] is False
    assert info["measurement"] == "off"
    assert set(info["unknown"]) == {"crowd_level", "difficulty", "has_park", "is_paved", "shade_level", "traffic_exposure"}
    assert any("측정하지 않아" in note for note in info["notes"])

    course = course_of(client, info["id"])
    assert course["is_personal"] is True
    assert course["is_familiar"] is True
    assert course["lighting"] == "unknown"
    assert course["data_sources"]["team_estimates"] == []
    assert 0.8 <= course["distance_km"] <= 1.1
    # 촘촘한 기록을 단순화해 저장하고, 출발점은 그대로다.
    assert len(course["route"]) < walk["point_count"] / 5
    assert course["route"][0] == list(START)
    assert any(f["type"] == "drinking_water" for f in course["facilities"])


def test_imported_walk_is_not_treated_as_familiar(client):
    walk = make_walk(client, source="imported", title="가져온 길")
    course = course_of(client, register(client, walk["id"]).json()["course"]["id"])
    assert course["is_familiar"] is False
    assert course["description"] == "GPX로 가져온 내 산책길이에요."


def test_unknown_values_are_never_shown_as_team_estimates_or_safe(client):
    walk = make_walk(client)
    course_id = register(client, walk["id"]).json()["course"]["id"]
    body = client.get("/api/safety", params={"pet_id": dubu_id(client), "course_id": course_id, "scenario": "heatwave"}).json()
    items = {item["key"]: item for item in body["assessment"]["items"]}
    for key in ("shade", "traffic", "surface", "park", "lighting"):
        assert items[key]["source"] == "unknown", key
        assert items[key]["value"] == "확인 불가", key
        assert items[key]["status"] != "ok", key
    # 더운 날 그늘을 모르면 주의로 본다.
    assert items["shade"]["status"] == "caution"


def test_long_course_with_unknown_shade_is_left_out_in_a_heatwave(client):
    walk = make_walk(client, route=out_and_back((37.5410, 126.9065)), title="긴 강변 길")
    course_id = register(client, walk["id"]).json()["course"]["id"]
    body = client.post("/api/recommendations", json={"pet_id": dubu_id(client), "weather_scenario": "heatwave"}).json()
    excluded = {item["course_id"]: item["reasons"] for item in body["excluded_courses"]}
    # 후보로 계산되었고, 그늘을 확인할 수 없어 제외되었다.
    assert course_id in excluded
    assert any("그늘" in reason for reason in excluded[course_id])


def test_my_course_is_explained_without_claims_it_cannot_back(client):
    walk = make_walk(client)
    course_id = register(client, walk["id"]).json()["course"]["id"]
    with SessionLocal() as db:
        data = to_course_data(db.get(WalkingCourse, course_id))
    # 내 코스만 후보로 넣어 늘 결과가 나오게 한다.
    result = recommend(make_pet(), [data], make_forecast(NOW), default_schedule(), EMPTY_STATE, NOW)
    top = result.courses[0]
    assert top.course.id == course_id
    assert "혼잡도: 확인 불가" in " ".join(top.explanation.details)
    assert "한적" not in top.explanation.summary
    assert "익숙한" in top.explanation.summary
    assert not any("비포장" in caution for caution in top.explanation.cautions)


def test_recommendation_payload_marks_my_course(client, monkeypatch):
    walk = make_walk(client)
    course_id = register(client, walk["id"]).json()["course"]["id"]
    from app.services import recommendation_service

    original = recommendation_service.active_courses
    monkeypatch.setattr(recommendation_service, "active_courses", lambda db, user: [c for c in original(db, user) if c.id == course_id])
    body = client.post("/api/recommendations", json={"pet_id": dubu_id(client), "weather_scenario": "rain_later"}).json()
    mine = body["courses"][0]
    assert mine["course_id"] == course_id
    assert mine["is_personal"] is True
    assert mine["safety"]["is_personal"] is True
    assert set(mine["safety"]["unknown"]) >= {"crowd_level", "is_paved"}


def test_registering_twice_updates_the_same_course(client):
    walk = make_walk(client)
    first = register(client, walk["id"]).json()["course"]["id"]
    client.patch(f"/api/my-walks/{walk['id']}", json={"title": "새 이름"})
    second = register(client, walk["id"]).json()["course"]["id"]
    assert first == second
    assert course_of(client, first)["name"] == "새 이름"


# ---------- 빼기와 삭제
def test_unregistered_course_leaves_recommendations_but_keeps_history(client):
    pet_id = dubu_id(client)
    walk = make_walk(client)
    course_id = register(client, walk["id"]).json()["course"]["id"]
    history = client.post("/api/walks", json={"pet_id": pet_id, "course_id": course_id, "duration_min": 15}).json()
    detail = client.delete(f"/api/my-walks/{walk['id']}/course").json()
    assert detail["course"]["active"] is False
    assert course_of(client, course_id) is None
    # 지난 기록과 길 안내는 주인에게 계속 열린다.
    assert client.get(f"/api/courses/{course_id}").status_code == 200
    assert any(item["id"] == history["id"] and item["course_name"] == "망원정마당 다녀오기" for item in client.get("/api/walks").json())
    assert register(client, walk["id"]).json()["course"]["active"] is True
    assert course_of(client, course_id) is not None


def test_deleting_the_walk_turns_the_course_off(client):
    walk = make_walk(client)
    course_id = register(client, walk["id"]).json()["course"]["id"]
    assert client.delete(f"/api/my-walks/{walk['id']}").status_code == 204
    assert course_of(client, course_id) is None
    assert client.get(f"/api/courses/{course_id}").status_code == 200


# ---------- 권한
def test_other_accounts_and_guests_cannot_see_or_use_my_course(client):
    alice = TestClient(app)
    signup(alice, "alice")
    alice_pet = alice.post("/api/pets", json=PET_BODY).json()
    walk = make_walk(alice, route=out_and_back((37.5410, 126.9065)), title="앨리스의 길")
    course_id = register(alice, walk["id"]).json()["course"]["id"]
    assert course_of(alice, course_id)["is_personal"] is True
    assert alice.get(f"/api/courses/{course_id}/nearby").status_code == 200

    bob = TestClient(app)
    signup(bob, "bob")
    bob_pet = bob.post("/api/pets", json=PET_BODY).json()
    for intruder, pet_id in ((bob, bob_pet["id"]), (client, dubu_id(client))):
        assert course_of(intruder, course_id) is None
        checks = [
            intruder.get(f"/api/courses/{course_id}"),
            intruder.post(f"/api/courses/{course_id}/approach", json={"latitude": START[0], "longitude": START[1]}),
            intruder.get(f"/api/courses/{course_id}/nearby"),
            intruder.get("/api/safety", params={"pet_id": pet_id, "course_id": course_id}),
            intruder.post("/api/walks", json={"pet_id": pet_id, "course_id": course_id, "duration_min": 20}),
            intruder.post("/api/routes/alternative", json={"pet_id": pet_id, "course_id": course_id, "progress_m": 0, "weather_scenario": "rain_now"}),
            intruder.post(f"/api/my-walks/{walk['id']}/course"),
        ]
        assert [response.status_code for response in checks] == [404] * len(checks)
        hot = intruder.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": "heatwave"}).json()
        assert course_id not in [item["course_id"] for item in hot["courses"] + hot["excluded_courses"]]
    # 주인에게는 후보로 계산된다.
    mine = alice.post("/api/recommendations", json={"pet_id": alice_pet["id"], "weather_scenario": "heatwave"}).json()
    assert course_id in [item["course_id"] for item in mine["courses"] + mine["excluded_courses"]]


def test_alternatives_during_a_walk_never_offer_someone_elses_course(client):
    alice = TestClient(app)
    signup(alice, "alice")
    walk = make_walk(alice)
    course_id = register(alice, walk["id"]).json()["course"]["id"]
    seed = client.get("/api/courses").json()[0]
    body = client.post(
        "/api/routes/alternative",
        json={"pet_id": dubu_id(client), "course_id": seed["id"], "latitude": START[0], "longitude": START[1], "progress_m": 100, "weather_scenario": "rain_later"},
    ).json()
    assert course_id not in [item["course_id"] for item in body["alternatives"]]


def test_course_list_stays_public_in_required_mode(client, monkeypatch):
    walk = make_walk(client)
    course_id = register(client, walk["id"]).json()["course"]["id"]
    monkeypatch.setattr(get_settings(), "auth_required", True)
    guest = TestClient(app)
    courses = guest.get("/api/courses")
    assert courses.status_code == 200
    assert course_id not in [course["id"] for course in courses.json()]
    assert guest.get(f"/api/courses/{course_id}").status_code == 404


# ---------- 거부
@pytest.mark.parametrize(
    "route, message",
    [
        (line((35.1530, 129.1185), (35.1570, 129.1185)) + line((35.1570, 129.1185), (35.1530, 129.1185)), "서비스 지역"),
        (line(START, (37.5545, 126.9068)), "100m보다 짧은"),
        (out_and_back((37.5045, 126.9065)), "10km까지"),
    ],
)
def test_walks_that_cannot_be_courses_are_refused_with_a_reason(client, route, message):
    walk = make_walk(client, route=route)
    response = register(client, walk["id"])
    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert client.get(f"/api/my-walks/{walk['id']}").json()["course"] is None


def test_paused_pieces_are_joined_when_close_and_refused_when_far(client):
    near = points(line(START, PARK), segment=0) + points(line((37.55125, 126.90345), START) + [START], segment=1)
    walk = client.post("/api/my-walks", json={"title": "쉬었다 간 길", "points": near}).json()
    assert register(client, walk["id"]).status_code == 200
    far = points(line(START, PARK), segment=0) + points(line((37.5480, 126.8990), (37.5470, 126.8970)), segment=1)
    walk = client.post("/api/my-walks", json={"title": "끊긴 길", "points": far}).json()
    response = register(client, walk["id"])
    assert response.status_code == 422
    assert "끊긴 구간" in response.json()["detail"]


# ---------- OSM 측정
def overpass_elements(route):
    lats = [p[0] for p in route]
    lngs = [p[1] for p in route]
    box = [(min(lats) - 0.001, min(lngs) - 0.001), (min(lats) - 0.001, max(lngs) + 0.001), (max(lats) + 0.001, max(lngs) + 0.001), (max(lats) + 0.001, min(lngs) - 0.001)]
    return [
        {"type": "way", "id": 1, "tags": {"highway": "footway", "lit": "yes", "surface": "asphalt"}, "geometry": [{"lat": a, "lon": b} for a, b in route]},
        {"type": "way", "id": 2, "tags": {"leisure": "park", "name": "가짜 공원"}, "geometry": [{"lat": a, "lon": b} for a, b in box + box[:1]]},
        *({"type": "node", "id": 100 + i, "lat": a, "lon": b, "tags": {"natural": "tree"}} for i, (a, b) in enumerate(route[::3])),
    ]


@pytest.fixture
def overpass(monkeypatch):
    calls = []
    state = {"fail": False}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if state["fail"]:
            return httpx.Response(504, text="timeout")
        return httpx.Response(200, json={"elements": overpass_elements(out_and_back(PARK))})

    monkeypatch.setattr(get_settings(), "environment_provider", "overpass")
    monkeypatch.setattr(environment_service, "TRANSPORT", httpx.MockTransport(handler))
    return {"calls": calls, "state": state}


def test_osm_measurement_fills_in_real_values(client, overpass):
    walk = make_walk(client)
    # 등록 응답은 바로 오고, 측정은 그 뒤에 끝난다.
    assert register(client, walk["id"]).json()["course"]["measurement"] == "pending"
    info = client.get(f"/api/my-walks/{walk['id']}").json()["course"]
    assert info["measurement"] == "done"
    assert info["environment_measured"] is True
    assert sorted(info["unknown"]) == ["crowd_level", "difficulty"]
    course = course_of(client, info["id"])
    assert course["environment"]["road"]["pedestrian"] == 1.0
    assert course["traffic_exposure"] == "low"
    assert course["lighting"] == "good"
    assert course["is_paved"] is True and course["surface_note"].startswith("OSM 기록")
    assert course["has_park"] is True
    assert course["shade_level"] >= 0.5
    body = client.get("/api/safety", params={"pet_id": dubu_id(client), "course_id": info["id"]}).json()
    items = {item["key"]: item for item in body["assessment"]["items"]}
    assert {items[key]["source"] for key in ("traffic", "surface", "lighting", "shade", "park")} == {"observed"}


def test_osm_failure_still_registers_with_unknown_values(client, overpass):
    overpass["state"]["fail"] = True
    walk = make_walk(client)
    response = register(client, walk["id"])
    assert response.status_code == 200
    info = client.get(f"/api/my-walks/{walk['id']}").json()["course"]
    assert info["measurement"] == "failed"
    assert info["environment_measured"] is False
    assert any("다시 측정" in note for note in info["notes"])
    assert len(overpass["calls"]) == len(environment_service.OVERPASS_MIRRORS)
    assert course_of(client, info["id"])["data_sources"]["environment_unavailable"].startswith("OSM 응답 실패")


# ---------- 단위
def test_simplify_keeps_the_shape_with_far_fewer_points():
    route = [list(point) for point in out_and_back(PARK)]
    simple = user_course_service.simplify(route)
    assert simple[0] == route[0] and simple[-1] == route[-1]
    assert len(simple) <= 6
    assert abs(user_course_service.route_km(simple) - user_course_service.route_km(route)) < 0.01


def test_unknown_slope_gets_a_caution_for_older_dogs():
    course = seed_course_data()[0]
    unknown = type(course)(**{**course.__dict__, "unknown": frozenset({"difficulty"}), "difficulty": "easy"})
    senior = make_pet(age_years=13)
    slot = type("Slot", (), {"fits_window": True, "window": None})()
    cautions = non_environment_cautions(senior, build_features(senior), unknown, slot)
    assert any("경사 정보가 없는" in caution for caution in cautions)
    assert not non_environment_cautions(make_pet(), build_features(make_pet()), unknown, slot)


def test_old_database_courses_stay_active_after_the_new_columns_are_added(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    Base.metadata.create_all(engine)
    raw = json.loads((user_course_service.__file__.replace("services/user_course_service.py", "data/courses.json"))
                     and open(user_course_service.__file__.replace("services/user_course_service.py", "data/courses.json"), encoding="utf-8").read())[0]
    with engine.begin() as connection:
        kept = [row[1] for row in connection.execute(text("PRAGMA table_info(walking_courses)")) if row[1] not in ("owner_user_id", "saved_walk_id", "is_active")]
        connection.execute(text(f"CREATE TABLE old_courses AS SELECT {', '.join(kept)} FROM walking_courses"))
        connection.execute(text("DROP TABLE walking_courses"))
        connection.execute(text("ALTER TABLE old_courses RENAME TO walking_courses"))
        columns = {key: (json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value) for key, value in raw.items()}
        connection.execute(text(f"INSERT INTO walking_courses (id, {', '.join(columns)}) VALUES (1, {', '.join(':' + key for key in columns)})"), columns)
    assert "is_active" not in {column["name"] for column in inspect(engine).get_columns("walking_courses")}
    ensure_schema(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT is_active, owner_user_id FROM walking_courses WHERE id = 1")).one() == (1, None)


def test_stale_measurement_does_not_overwrite_a_newer_registration(client, overpass):
    walk = make_walk(client)
    course_id = register(client, walk["id"]).json()["course"]["id"]
    with SessionLocal() as db:
        course = db.get(WalkingCourse, course_id)
        course.data_sources = {**course.data_sources, "measurement": "newer-token", "environment_status": "pending", "unknown": ["crowd_level"]}
        course.environment = None
        db.commit()
    user_course_service.measure(course_id, "old-token")
    with SessionLocal() as db:
        course = db.get(WalkingCourse, course_id)
        assert course.environment is None
        assert course.data_sources["environment_status"] == "pending"


def test_measurement_that_never_finishes_is_reported_as_failed(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "environment_provider", "overpass")
    monkeypatch.setattr(user_course_service, "measure", lambda course_id, token: None)
    walk = make_walk(client)
    course_id = register(client, walk["id"]).json()["course"]["id"]
    assert client.get(f"/api/my-walks/{walk['id']}").json()["course"]["measurement"] == "pending"
    with SessionLocal() as db:
        course = db.get(WalkingCourse, course_id)
        course.data_sources = {**course.data_sources, "measurement_started": "2020-01-01T00:00:00"}
        db.commit()
    assert client.get(f"/api/my-walks/{walk['id']}").json()["course"]["measurement"] == "failed"


@pytest.mark.parametrize("share, expected", [(None, False), (0.0, False), (0.016, True), (0.184, True)])
def test_park_share_threshold_matches_the_team_labels(share, expected):
    attributes, unknown = user_course_service.course_attributes({"park": share} if share is not None else None, True)
    assert attributes["has_park"] is expected
    assert ("has_park" in unknown) is (share is None)

