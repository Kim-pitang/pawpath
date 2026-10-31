"""서비스 지역 전환. 지역마다 코스가 나뉘고, 기본값인 망원동 시연은 그대로다."""
import json
from pathlib import Path

import pytest

from app.config import SERVICE_AREAS, Settings, get_settings
from app.services.routing_service import haversine_m
from tests.test_api_e2e import FIVE_STARS, dubu_id

DATA_DIR = Path(__file__).parent.parent / "app" / "data"
MANGWON = SERVICE_AREAS["mangwon"]
GAEPO = SERVICE_AREAS["gaepo"]
GAEPO_COURSES = json.loads((DATA_DIR / "courses_gaepo.json").read_text(encoding="utf-8"))
GAEPO_NAMES = {course["name"] for course in GAEPO_COURSES}
MANGWON_CODES = [course["code"] for course in json.loads((DATA_DIR / "courses.json").read_text(encoding="utf-8"))]
REQUIRED_SENTENCE = "낯선 길을 싫어하는 두부를 위해 익숙한 공원 코스를 골랐어요. 비가 오기 전 짧게 다녀올 수 있어요."


@pytest.fixture
def gaepo(monkeypatch):
    monkeypatch.setenv("SERVICE_AREA", "gaepo")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def recommend(client, pet_id, scenario="rain_later"):
    return client.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": scenario}).json()


# ---------- 기본값은 그대로
def test_default_area_keeps_the_mangwon_courses_and_their_numbers(client):
    courses = client.get("/api/courses").json()
    assert [course["code"] for course in courses] == MANGWON_CODES
    assert [course["id"] for course in courses] == list(range(1, len(MANGWON_CODES) + 1))
    assert {course["area"] for course in courses} == {MANGWON.label}


def test_default_recommendation_never_mixes_in_other_areas(client):
    body = recommend(client, dubu_id(client))
    assert not {course["name"] for course in body["courses"]} & GAEPO_NAMES
    assert not {course["name"] for course in body["excluded_courses"]} & GAEPO_NAMES


# ---------- 설정
def test_weather_coordinates_follow_the_area_unless_set():
    settings = Settings(_env_file=None, service_area="gaepo")
    assert (settings.service_latitude, settings.service_longitude) == (GAEPO.latitude, GAEPO.longitude)
    assert settings.service_area_label == GAEPO.label
    custom = Settings(_env_file=None, service_area="gaepo", service_latitude=37.5, service_longitude=127.0)
    assert (custom.service_latitude, custom.service_longitude) == (37.5, 127.0)


def test_unknown_area_stops_the_server_with_a_clear_message():
    with pytest.raises(ValueError, match="SERVICE_AREA"):
        Settings(_env_file=None, service_area="busan")


# ---------- 개포동
def test_gaepo_area_lists_only_its_courses(gaepo, client):
    courses = client.get("/api/courses").json()
    assert {course["name"] for course in courses} == GAEPO_NAMES
    assert {course["area"] for course in courses} == {GAEPO.label}


def test_gaepo_recommendation_uses_only_its_courses_and_gives_the_same_reason(gaepo, client):
    body = recommend(client, dubu_id(client))
    assert len(body["courses"]) == 3
    assert {course["name"] for course in body["courses"]} <= GAEPO_NAMES
    assert body["courses"][0]["reason"]["summary"] == REQUIRED_SENTENCE


def test_gaepo_excludes_courses_in_a_heatwave_only_from_its_own(gaepo, client):
    body = recommend(client, dubu_id(client), "heatwave")
    assert body["excluded_courses"]
    assert {course["name"] for course in body["excluded_courses"]} <= GAEPO_NAMES


def test_five_stars_on_the_second_course_moves_it_to_first_in_gaepo(gaepo, client):
    pet_id = dubu_id(client)
    target = recommend(client, pet_id)["courses"][1]
    # v2는 피드백 1건을 보수적으로 반영해, 5점을 두 번 남겨야 1위로 오른다.
    for _ in range(2):
        walk = client.post("/api/walks", json={"pet_id": pet_id, "course_id": target["course_id"], "duration_min": target["duration_min"]}).json()
        client.post("/api/feedback", json={"walk_id": walk["id"], **FIVE_STARS})
    second = recommend(client, pet_id)
    assert second["courses"][0]["course_id"] == target["course_id"]
    assert second["courses"][0]["rank_change"] == 1


def test_alternatives_during_a_walk_stay_in_the_same_area(gaepo, client):
    pet_id = dubu_id(client)
    courses = client.get("/api/courses").json()
    body = client.post(
        "/api/routes/alternative",
        json={"pet_id": pet_id, "course_id": courses[-1]["id"], "latitude": GAEPO.latitude, "longitude": GAEPO.longitude, "progress_m": 100, "weather_scenario": "rain_later"},
    ).json()
    assert {item["name"] for item in body["alternatives"]} <= GAEPO_NAMES


def test_gaepo_nearby_places_come_from_collected_data(gaepo, client):
    course = client.get("/api/courses").json()[0]
    body = client.get(f"/api/courses/{course['id']}/nearby", params={"radius_m": 300}).json()
    assert body["places"]
    assert all(haversine_m((place["lat"], place["lng"]), (GAEPO.latitude, GAEPO.longitude)) < 5000 for place in body["places"])


# ---------- 코스 자료
@pytest.mark.parametrize("course", GAEPO_COURSES, ids=lambda course: course["code"])
def test_gaepo_course_data_is_walkable_from_the_venue_and_marks_its_estimates(course):
    assert course["area"] == GAEPO.label
    # 이 거리 안이어야 앱이 출발점까지 도보 경로를 안내한다.
    assert haversine_m((course["start_lat"], course["start_lng"]), (GAEPO.latitude, GAEPO.longitude)) <= 3000
    assert haversine_m(tuple(course["route"][0]), tuple(course["route"][-1])) < 30
    assert course["environment"]["road"] is not None
    assert "crowd_level" in course["data_sources"]["team_estimates"]
