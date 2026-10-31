"""고도화 지시서의 검증 시나리오 12개. 결과는 docs/VALIDATION.md에 정리한다.

7, 8번은 화면 동작까지 frontend/e2e/walk-navigation.spec.ts에서도 검증한다.
"""
from datetime import datetime

import httpx
import pytest

from app.config import Settings
from app.database import SessionLocal
from app.models import Pet, Recommendation
from app.recommender.engine import recommend
from app.recommender.features import build_features
from app.recommender.types import PreferenceState
from app.services.llm_service import LlmUnavailable, enhance_recommendation
from app.services.routing_service import OsrmFootRouter, plan_approach
from app.services.weather_providers import OpenMeteoProvider, scenario_forecast
from app.services.weather_service import get_weather
from app.recommender.types import TimeWindow
from tests.conftest import EMPTY_STATE, NOW, default_schedule, make_forecast, make_pet, seed_course_data
from tests.test_api_e2e import FIVE_STARS, dubu_id

COURSES = seed_course_data()


def run(pet=None, forecast=None, state=EMPTY_STATE, now=NOW, schedule=None):
    return recommend(pet or make_pet(), COURSES, forecast if forecast is not None else make_forecast(now), schedule or default_schedule(), state, now)


def test_01_new_user_gets_a_rule_based_recommendation(client):
    pet_id = dubu_id(client)
    body = client.post("/api/recommendations", json={"pet_id": pet_id}).json()
    assert body["learning"] == {"feedback_total": 0, "is_personalized": False, "mode": "rule_based", "ranker": "weighted-sum"}
    assert len(body["courses"]) == 3
    for course in body["courses"]:
        assert course["learning_delta"] == 0
        # 데이터가 없는 과거 피드백과 사용자 선호는 중립값으로 채우지 않고 반영하지 않았다고 밝힌다.
        groups = {g["key"]: g for g in course["score_groups"]}
        assert groups["feedback"]["available"] is False and groups["feedback"]["weight"] == 0
        assert groups["user_preference"]["available"] is False and groups["user_preference"]["weight"] == 0
        assert any("과거 선호도는 반영하지 않았어요" in item["text"] for item in course["reason"]["basis"])
        assert course["reason"]["summary"]
        assert course["safety_assessment"]["items"]


def test_02_high_energy_dog_gets_a_longer_course_than_a_calm_small_dog():
    calm = run().courses[0].course
    energetic_pet = make_pet(name="바람", size="large", weight_kg=28, activity_level="high", personality="active", path_preference="new", novelty_reaction="calm")
    energetic = run(energetic_pet)
    assert build_features(energetic_pet).ideal_distance_km > 4
    assert energetic.courses[0].course.distance_km > calm.distance_km
    assert energetic.courses[0].course.distance_km >= 2.5


def test_03_senior_dog_gets_a_shorter_flat_walk():
    adult = make_pet(size="large", weight_kg=28, age_years=4, personality="active", path_preference="new", novelty_reaction="calm")
    senior = make_pet(size="large", weight_kg=28, age_years=11, personality="active", path_preference="new", novelty_reaction="calm")
    schedule = default_schedule(preferred_duration_min=120)
    adult_result = run(adult, schedule=schedule)
    senior_result = run(senior, schedule=schedule)
    assert build_features(senior).life_stage == "senior"
    assert senior_result.time.recommended_duration_min < adult_result.time.recommended_duration_min
    assert senior_result.courses[0].course.distance_km <= adult_result.courses[0].course.distance_km
    assert all(item.course.difficulty == "easy" for item in senior_result.courses)


def test_04_rainy_day_avoids_rain_and_slippery_courses():
    # 첫 출발 1시간 뒤부터 비가 오면 짧은 코스를 비 오기 전에 다녀오게 한다.
    forecast = scenario_forecast("rain_later", NOW, NOW.replace(hour=16))
    before_rain = run(forecast=forecast)
    top = before_rain.courses[0]
    assert top.slot.start.hour == 16
    assert top.slot.rain_overlap_min == 0
    assert "비가 오기 전" in top.explanation.summary
    # 내내 비가 오면 비포장 코스는 제외하고 이유를 알려 준다.
    all_rain = run(forecast=scenario_forecast("rain_now", NOW, NOW.replace(hour=16)))
    excluded = {item.course.name: item.reasons for item in all_rain.excluded}
    assert "성미산 숲길" in excluded
    assert any("미끄러" in reason for reason in excluded["성미산 숲길"])
    assert all(item.course.is_paved for item in all_rain.courses)
    assert all(item.safety.level != "good" for item in all_rain.courses)


def test_05_heat_excludes_risky_courses_and_offers_safer_ones():
    forecast = scenario_forecast("heatwave", NOW, NOW.replace(hour=16))
    result = run(forecast=forecast)
    assert result.walkable is True
    # 더운 시간대는 제외하고 해 질 무렵만 남긴다.
    assert all(item.slot.start.hour == 19 for item in result.courses)
    assert any(slot.unsafe_reason for slot in result.time.all_slots)
    # 그늘을 확인할 수 없는 긴 코스는 제외한다.
    excluded = {item.course.name: item.reasons for item in result.excluded}
    assert excluded
    assert any("그늘" in reason or "더위" in reason for reasons in excluded.values() for reason in reasons)
    assert all(item.course.duration_min <= 30 or item.course.shade_level >= 0.6 for item in result.courses)
    assert all(item.safety.level in ("caution", "danger") for item in result.courses)
    assert any("노면" in risk for item in result.courses for risk in item.safety.risks)


def test_06_past_satisfaction_changes_the_ranking(client):
    pet_id = dubu_id(client)
    first = client.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": "rain_later"}).json()
    target = first["courses"][1]
    second = first
    for _ in range(2):
        walk = client.post("/api/walks", json={"pet_id": pet_id, "course_id": target["course_id"], "duration_min": target["duration_min"], "recommendation_id": second["id"]}).json()
        client.post("/api/feedback", json={"walk_id": walk["id"], **FIVE_STARS})
        second = client.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": "rain_later"}).json()
    # 5점 두 번이면 2위 코스가 1위로 오른다.
    assert second["learning"]["mode"] == "personalized"
    assert second["courses"][0]["course_id"] == target["course_id"]
    assert second["courses"][0]["rank_change"] == 1
    assert second["courses"][0]["learning_delta"] > 0


def test_07_gps_denied_gets_a_clear_message_instead_of_a_route(client):
    pet_id = dubu_id(client)
    course_id = client.get("/api/courses").json()[0]["id"]
    body = client.post("/api/routes/alternative", json={"pet_id": pet_id, "course_id": course_id, "weather_scenario": "rain_now"}).json()
    assert body["action"] == "no_location"
    assert body["return_route"] is None
    assert "위치 권한" in body["location_notice"]
    # 위치가 없어도 날씨 판단과 대체 코스 안내는 유지한다.
    assert body["status"] == "shorten"
    assert body["assessment"]["items"]


def test_08_moving_changes_the_route_guidance(client):
    course = client.get("/api/courses").json()[0]
    near = client.post(f"/api/courses/{course['id']}/approach", json={"latitude": course["start_lat"] + 0.002, "longitude": course["start_lng"]}).json()
    closer = client.post(f"/api/courses/{course['id']}/approach", json={"latitude": course["start_lat"] + 0.0005, "longitude": course["start_lng"]}).json()
    far = client.post(f"/api/courses/{course['id']}/approach", json={"latitude": 37.4979, "longitude": 127.0276}).json()
    assert closer["distance_m"] < near["distance_m"]
    assert near["route"][0] != closer["route"][0]
    assert far["mode"] == "too_far"


def test_09_weather_change_during_a_walk_changes_the_advice(client):
    pet_id = dubu_id(client)
    course = client.get("/api/courses").json()[0]
    position = {"latitude": course["start_lat"] + 0.001, "longitude": course["start_lng"]}
    rain = client.post("/api/routes/alternative", json={"pet_id": pet_id, "course_id": course["id"], "progress_m": 600, **position, "weather_scenario": "rain_now"}).json()
    assert rain["status"] == "shorten"
    assert rain["return_route"]["route"]
    assert rain["action"] == "return_to_start"
    storm = client.post("/api/routes/alternative", json={"pet_id": pet_id, "course_id": course["id"], "progress_m": 600, **position, "weather_scenario": "heavy_rain"}).json()
    assert storm["status"] == "return_now"


def test_10_llm_outage_keeps_the_recommendation_and_template(client):
    class DownProvider:
        name = "ollama"
        model = "down"

        def complete(self, system, user, schema):
            raise LlmUnavailable("ConnectError")

    pet_id = dubu_id(client)
    created = client.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": "rain_later"}).json()
    with SessionLocal() as db:
        record = db.get(Recommendation, created["id"])
        payload = enhance_recommendation(db, record, db.get(Pet, pet_id), DownProvider()).payload
    assert payload["explanation_engine"]["status"] == "failed"
    assert payload["courses"][0]["reason"]["summary"] == created["courses"][0]["reason"]["summary"]
    assert payload["courses"][0]["total_score"] == created["courses"][0]["total_score"]


def test_11_external_api_outages_fall_back(client):
    # 날씨 API 장애: 모의 날씨로 추천을 계속하고 화면에 알린다.
    down = OpenMeteoProvider("Asia/Seoul", 1.0, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    now = datetime(2026, 10, 30, 10, 0)
    with SessionLocal() as db:
        weather = get_weather(db, now, (TimeWindow(16, 20),), provider=down, settings=Settings(weather_provider="open-meteo"))
    assert weather.is_mock and weather.source == "mock-fallback" and weather.notice
    assert recommend(make_pet(), COURSES, weather.hours, default_schedule(), PreferenceState(), now, weather_source="demo").courses

    # 길찾기 API 장애: 직선으로 표시하고 안내한다.
    router = OsrmFootRouter("https://example.test", 1.0, client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    plan = plan_approach((37.556, 126.9105), (37.5545, 126.9065), router=router, settings=Settings(routing_provider="osrm"))
    assert plan.mode == "straight" and plan.notice


def test_12_finishing_a_walk_creates_a_report(client):
    pet_id = dubu_id(client)
    recommendation = client.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": "rain_later"}).json()
    top = recommendation["courses"][0]
    walk = client.post(
        "/api/walks",
        json={"pet_id": pet_id, "course_id": top["course_id"], "recommendation_id": recommendation["id"], "duration_min": 24, "tracking_source": "gps", "distance_km": 1.3},
    ).json()
    client.post("/api/feedback", json={"walk_id": walk["id"], **FIVE_STARS})

    report = client.get("/api/walks/report", params={"pet_id": pet_id}).json()
    assert report["summary"]["walk_count"] == 1
    assert report["summary"]["total_distance_km"] == 1.3
    assert report["summary"]["total_minutes"] == 24
    assert report["summary"]["average_pet_rating"] == 5
    assert report["favorite_courses"][0]["course_id"] == top["course_id"]
    assert report["recommendation_vs_actual"]["followed_top_count"] == 1
    assert sum(day["walk_count"] for day in report["daily"]) == 1
    assert report["satisfaction_trend"][0]["pet_rating"] == 5
