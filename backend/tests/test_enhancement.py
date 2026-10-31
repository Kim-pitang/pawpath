"""설정 가능한 가중치, 사용자 선호도, DB 호환, 시설, 대체 경로, 리포트."""
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

from app.config import Settings
from app.database import Base, SessionLocal
from app.migrations import ADDED_COLUMNS, ensure_schema
from app.models import Pet, User, WalkingCourse
from app.recommender.config import BASE_WEIGHTS, DEFAULT_CONFIG, V1, ScoringConfig, parse_scoring_config
from app.recommender.engine import recommend
from app.recommender.features import build_features
from app.recommender.preference import apply_feedback, preferred_time_match, record_visit, user_preference_score
from app.recommender.types import FeedbackInput, TimeWindow
from app.services import places_service
from app.services.alternative_service import evaluate_alternative
from app.services.weather_service import WeatherResult
from tests.conftest import EMPTY_STATE, NOW, default_schedule, make_course, make_forecast, make_pet, seed_course_data
from tests.test_api_e2e import FIVE_STARS, PET_BODY, dubu_id

COURSES = seed_course_data()
FIXED_NOON = datetime(2026, 10, 30, 12, 0)


# ---------- 환경변수
def test_blank_environment_values_fall_back_to_defaults(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("WEATHER_CACHE_MINUTES=\nLLM_TIMEOUT_SECONDS=\nSEED_DEMO_PET=\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SEED_DEMO_PET")
    settings = Settings()
    assert settings.weather_cache_minutes == 30
    assert settings.llm_timeout_seconds == 60
    assert settings.seed_demo_pet is True


def test_env_example_matches_the_settings_and_can_be_used_as_is():
    root = Path(__file__).parent.parent.parent
    lines = [line for line in (root / ".env.example").read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
    documented = {line.split("=", 1)[0].lower() for line in lines}
    assert documented == set(Settings.model_fields)
    # 예시 파일을 그대로 복사해도 설정이 읽힌다.
    assert Settings(_env_file=root / ".env.example").llm_provider == "none"


def test_readme_lists_every_setting():
    root = Path(__file__).parent.parent.parent
    readme = (root / "README.md").read_text(encoding="utf-8")
    for name in Settings.model_fields:
        assert f"`{name.upper()}`" in readme, name


# ---------- 가중치 설정
def test_empty_setting_uses_the_default_weights():
    assert parse_scoring_config("") is DEFAULT_CONFIG


def test_custom_weights_are_normalized():
    config = parse_scoring_config('{"weather": 0.5, "safety": 0.5, "user_preference": 0.2}')
    assert sum(config.weights.values()) == pytest.approx(1.0)
    assert config.weights["weather"] > BASE_WEIGHTS["weather"]
    assert config.user_preference_weight == 0.2


@pytest.mark.parametrize("raw", ['{"typo": 1}', '{"weather": -1}', '{"weather": "많이"}', "[1, 2]", '{"weather": 0, "personality": 0, "activity": 0, "schedule": 0, "safety": 0, "preference": 0}'])
def test_invalid_weights_are_rejected(raw):
    with pytest.raises(ValueError):
        parse_scoring_config(raw)


def test_invalid_json_is_rejected():
    with pytest.raises(ValueError):
        parse_scoring_config("{not json")


def test_changing_weights_changes_the_ranking():
    pet = make_pet(size="large", weight_kg=28, activity_level="high", personality="active", path_preference="new", novelty_reaction="calm")
    run = lambda config: [item.course.id for item in recommend(pet, COURSES, make_forecast(), default_schedule(), EMPTY_STATE, NOW, config=config).courses]  # noqa: E731
    activity_only = parse_scoring_config('{"weather": 0, "personality": 0, "activity": 1, "schedule": 0, "safety": 0, "preference": 0}', V1)
    schedule_only = parse_scoring_config('{"weather": 0, "personality": 0, "activity": 0, "schedule": 1, "safety": 0, "preference": 0}', V1)
    assert run(activity_only) != run(schedule_only)
    # v2는 묶음 이름으로 바꾼다.
    pet_only = parse_scoring_config('{"pet_fit": 1, "user_preference": 0, "distance_time": 0, "weather_env": 0}')
    time_only = parse_scoring_config('{"pet_fit": 0, "user_preference": 0, "distance_time": 1, "weather_env": 0}')
    assert run(pet_only) != run(time_only)


def test_ranker_can_be_replaced_without_touching_the_engine():
    class ShortestFirst:
        name = "stub-model"

        def score(self, contributions, factor_scores, penalty):
            return factor_scores["activity"]

    result = recommend(make_pet(), COURSES, make_forecast(), default_schedule(), EMPTY_STATE, NOW, config=ScoringConfig(ranker=ShortestFirst(), version=V1))
    assert result.ranker == "stub-model"
    scores = [next(f.score for f in item.factors if f.key == "activity") for item in result.courses]
    assert scores == sorted(scores, reverse=True)


def test_ranker_can_be_replaced_in_v2_and_receives_group_scores():
    class PetFitOnly:
        name = "stub-model"

        def score(self, contributions, factor_scores, penalty):
            return factor_scores["pet_fit"]

    result = recommend(make_pet(), COURSES, make_forecast(), default_schedule(), EMPTY_STATE, NOW, config=ScoringConfig(ranker=PetFitOnly()))
    assert result.ranker == "stub-model"
    scores = [next(g.score for g in item.groups if g.key == "pet_fit") for item in result.courses]
    assert scores == sorted(scores, reverse=True)


def test_alternative_is_offered_only_when_it_is_meaningfully_safer():
    from app.services.weather_providers import scenario_forecast

    # 권한다면 위험 수준이 낮거나 안전 점수가 충분히 높아야 한다.
    rainy = recommend(make_pet(), COURSES, scenario_forecast("rain_later", NOW, NOW.replace(hour=16)), default_schedule(), EMPTY_STATE, NOW)
    rows = {course.id: course for course in COURSES}
    for item in rainy.courses:
        if item.alternative is not None:
            assert item.alternative.id in rows
    # 안전 점수 차이가 작으면 권하지 않는다.
    close_a = make_course(1, name="가", lighting="partial")
    close_b = make_course(2, name="나", lighting="partial", facility_counts={"toilets": 1})
    similar = recommend(make_pet(), [close_a, close_b], scenario_forecast("rain_later", NOW, NOW.replace(hour=16)), default_schedule(), EMPTY_STATE, NOW)
    assert all(item.alternative is None for item in similar.courses)
    # 조명 기록이 있는 코스와 어두운 코스가 섞이면 실제로 더 안전한 쪽을 권한다.
    from app.recommender.types import TimeWindow as Window

    dark_schedule = default_schedule(windows=(Window(19, 20),))
    lit = make_course(1, name="밝은 길", crowd_level="medium", environment={"lit": {"yes": 0.9, "no": 0.0, "unknown": 0.1}})
    dim = make_course(2, name="어두운 길", lighting="partial")
    bold = make_pet(personality="active", novelty_reaction="calm")
    result = recommend(bold, [dim, lit], make_forecast(), dark_schedule, EMPTY_STATE, NOW)
    by_name = {item.course.name: item for item in result.courses}
    assert by_name["어두운 길"].safety.level == "caution"
    assert by_name["어두운 길"].alternative is not None and by_name["어두운 길"].alternative.name == "밝은 길"


def test_excluded_course_reason_names_what_is_specific_to_that_course():
    from app.services.weather_providers import scenario_forecast

    result = recommend(make_pet(), COURSES, scenario_forecast("heatwave", NOW, NOW.replace(hour=16)), default_schedule(), EMPTY_STATE, NOW)
    for item in result.excluded:
        assert not any(reason.endswith("의 더위") for reason in item.reasons), item.reasons
        assert len(item.reasons) <= 2


def test_other_cautions_do_not_repeat_the_safety_risks(client):
    pet_id = dubu_id(client)
    top = client.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": "rain_later"}).json()["courses"][0]
    assert any("비 예보" in risk for risk in top["safety_assessment"]["risks"])
    assert not any("비 예보" in caution for caution in top["other_cautions"])
    # 기존 필드는 그대로 유지한다.
    assert any("비 예보" in caution for caution in top["cautions"])


# ---------- 사용자 선호도
def test_no_preference_data_is_neutral():
    score, evidence = user_preference_score(make_course(), 16, build_features(make_pet()), EMPTY_STATE)
    assert score == 50
    assert "입력하면" in evidence[0]


def test_preferred_distance_favors_matching_courses():
    features = build_features(make_pet(preferred_distance_km=3.5))
    near, _ = user_preference_score(make_course(distance_km=3.4), 16, features, EMPTY_STATE)
    far, _ = user_preference_score(make_course(distance_km=1.0), 16, features, EMPTY_STATE)
    assert near > 90 > far


def test_preferred_time_match_levels():
    assert preferred_time_match(None, 16) is None
    assert preferred_time_match("afternoon", 16) == 100
    assert preferred_time_match("afternoon", 19) == 60
    assert preferred_time_match("morning", 19) == 30


def test_selection_history_raises_the_chosen_course_only_for_pets_who_like_familiar_paths():
    state = record_visit(record_visit(EMPTY_STATE, 1), 1)
    timid = build_features(make_pet())
    explorer = build_features(make_pet(path_preference="new", personality="curious", novelty_reaction="calm"))
    timid_score, evidence = user_preference_score(make_course(1), 16, timid, state)
    explorer_score, _ = user_preference_score(make_course(1), 16, explorer, state)
    # 새로운 길을 좋아할수록 지금까지의 선택에 덜 묶인다.
    assert timid_score > explorer_score >= 50
    assert "2번 중 2번" in evidence[0]


def test_disliked_course_gets_no_credit_for_being_chosen():
    course = make_course(1)
    state = apply_feedback(record_visit(EMPTY_STATE, 1), course, FeedbackInput(1, 1, "hard", 5, False), 16)
    score, _ = user_preference_score(course, 16, build_features(make_pet()), state)
    assert score == 50


def test_preferences_are_not_counted_as_learning():
    pet = make_pet(preferred_distance_km=3.5)
    for item in recommend(pet, COURSES, make_forecast(), default_schedule(), EMPTY_STATE, NOW).courses:
        assert item.total_score == item.baseline_score


def test_preferred_distance_and_time_change_recommendations():
    schedule = default_schedule(windows=(TimeWindow(8, 10), TimeWindow(16, 18)))
    now = datetime(2026, 10, 30, 7, 0)
    forecast = make_forecast(now)
    base = recommend(make_pet(), COURSES, forecast, schedule, EMPTY_STATE, now)
    distance = recommend(make_pet(preferred_distance_km=3.7), COURSES, forecast, schedule, EMPTY_STATE, now)
    assert distance.courses[0].course.distance_km >= base.courses[0].course.distance_km
    evening = recommend(make_pet(preferred_time_bucket="afternoon"), COURSES, forecast, schedule, EMPTY_STATE, now)
    assert all(item.slot.start.hour >= 16 for item in evening.courses)
    assert evening.time.best_slots[0].start.hour >= 16


def test_pet_api_stores_preferences_and_old_clients_do_not_erase_them(client):
    body = {**PET_BODY, "preferred_distance_km": 2.5, "preferred_time_bucket": "evening"}
    created = client.post("/api/pets", json=body).json()
    assert created["preferred_distance_km"] == 2.5
    # 새 필드를 모르는 예전 클라이언트의 수정 요청
    updated = client.put(f"/api/pets/{created['id']}", json={**PET_BODY, "weight_kg": 11}).json()
    assert updated["weight_kg"] == 11
    assert updated["preferred_distance_km"] == 2.5
    assert updated["preferred_time_bucket"] == "evening"
    # 새 클라이언트는 비울 수 있다.
    cleared = client.put(f"/api/pets/{created['id']}", json={**PET_BODY, "preferred_distance_km": None}).json()
    assert cleared["preferred_distance_km"] is None
    assert client.post("/api/pets", json={**PET_BODY, "preferred_time_bucket": "midnight"}).status_code == 422
    assert client.post("/api/pets", json={**PET_BODY, "preferred_distance_km": 0}).status_code == 422


# ---------- DB 호환
def _old_schema_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/old.db")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for table, columns in ADDED_COLUMNS.items():
            # SQLite는 외래 키가 걸린 컬럼을 지울 수 없어, 새 컬럼을 뺀 표를 새로 만든다. 색인도 함께 사라진다.
            added = {name for name, _ in columns}
            kept = [row[1] for row in connection.execute(text(f"PRAGMA table_info({table})")) if row[1] not in added]
            connection.execute(text(f"CREATE TABLE {table}_old AS SELECT {', '.join(kept)} FROM {table}"))
            connection.execute(text(f"DROP TABLE {table}"))
            connection.execute(text(f"ALTER TABLE {table}_old RENAME TO {table}"))
        connection.execute(text("INSERT INTO users (id, name, available_windows, preferred_duration_min, walks_per_day, created_at, updated_at) VALUES (1, '보호자', '[]', 40, 1, '2026-10-30', '2026-10-30')"))
        connection.execute(text("INSERT INTO pets (id, user_id, name, breed, age_years, weight_kg, size, activity_level, personality, path_preference, heat_sensitivity, novelty_reaction, learned_attribute_weights, learned_time_buckets, feedback_total, created_at, updated_at) VALUES (1, 1, '옛날두부', '말티즈', 5, 4, 'small', 'medium', 'timid', 'familiar', 'medium', 'anxious', '{}', '{}', 3, '2026-10-30', '2026-10-30')"))
    return engine


def test_old_database_gets_new_columns_and_keeps_its_data(tmp_path):
    engine = _old_schema_engine(tmp_path)
    assert "preferred_distance_km" not in {c["name"] for c in inspect(engine).get_columns("pets")}
    added = ensure_schema(engine)
    assert "pets.preferred_distance_km" in added
    assert "walk_histories.tracking_source" in added
    assert "walking_courses.environment" in added
    assert "users.login_id" in added
    assert "users.google_sub" in added
    assert {"walking_courses.owner_user_id", "walking_courses.saved_walk_id", "walking_courses.is_active"} <= set(added)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT name, feedback_total, preferred_distance_km FROM pets")).one()
        assert connection.execute(text("SELECT login_id, password_hash FROM users WHERE id = 1")).one() == (None, None)
    assert row == ("옛날두부", 3, None)
    # 아이디 중복을 막는 고유 색인도 함께 생긴다.
    indexes = {index["name"]: index["unique"] for index in inspect(engine).get_indexes("users")}
    assert indexes.get("ix_users_login_id") and indexes.get("ix_users_google_sub")


def test_migration_can_run_repeatedly(tmp_path):
    engine = _old_schema_engine(tmp_path)
    ensure_schema(engine)
    assert ensure_schema(engine) == []


def test_new_database_needs_no_column_changes(tmp_path):
    assert ensure_schema(create_engine(f"sqlite:///{tmp_path}/new.db")) == []


# ---------- 주변 시설
@pytest.fixture
def sample_places(monkeypatch):
    def fake():
        return {
            "collected_on": "2026-10-31",
            "unavailable_types": ["dog_park"],
            "places": [
                {"type": "veterinary", "name": "가까운 동물병원", "lat": 37.5545, "lng": 126.9066},
                {"type": "veterinary", "name": "먼 동물병원", "lat": 37.60, "lng": 126.99},
                {"type": "pet_friendly", "name": "동반 표시 카페", "lat": 37.5546, "lng": 126.9067},
                {"type": "pet_friendly", "name": "동반 표시 카페", "lat": 37.5546, "lng": 126.9067},
            ],
        }

    monkeypatch.setattr(places_service, "load_places", fake)


def test_nearby_filters_by_distance_and_type_and_marks_pet_access_as_unconfirmed(client, sample_places):
    course = client.get("/api/courses").json()[0]
    body = client.get(f"/api/courses/{course['id']}/nearby", params={"radius_m": 300}).json()
    names = [place["name"] for place in body["places"]]
    assert "가까운 동물병원" in names
    assert "먼 동물병원" not in names
    assert names.count("동반 표시 카페") == 1
    friendly = next(place for place in body["places"] if place["type"] == "pet_friendly")
    assert "실제 동반 가능 여부" in friendly["note"]
    assert body["source"] == "OpenStreetMap"
    assert body["unavailable_types"] == ["dog_park"]
    only_vet = client.get(f"/api/courses/{course['id']}/nearby", params={"types": "veterinary"}).json()
    assert {place["type"] for place in only_vet["places"]} == {"veterinary"}


def test_nearby_validates_input(client):
    assert client.get("/api/courses/999/nearby").status_code == 404
    assert client.get("/api/courses/1/nearby", params={"types": "casino"}).status_code == 422
    assert client.get("/api/courses/1/nearby", params={"radius_m": 5}).status_code == 422


# ---------- 안전 지수 API
def test_safety_endpoint_for_conditions_and_course(client):
    pet_id = dubu_id(client)
    current = client.get("/api/safety", params={"pet_id": pet_id}).json()
    assert current["course_id"] is None
    assert current["assessment"]["items"]
    assert current["weather"]["is_mock"] is True
    assert "보장하지" in current["assessment"]["disclaimer"]
    course = client.get("/api/courses").json()[0]
    detailed = client.get("/api/safety", params={"pet_id": pet_id, "course_id": course["id"], "scenario": "rain_now"}).json()
    assert detailed["course_id"] == course["id"]
    assert any(item["key"] == "lighting" for item in detailed["assessment"]["items"])
    assert detailed["assessment"]["level"] != "good"
    assert client.get("/api/safety", params={"pet_id": 999}).status_code == 404
    assert client.get("/api/safety", params={"pet_id": pet_id, "course_id": 999}).status_code == 404


def test_recommendation_includes_safety_and_personalization_mode(client):
    pet_id = dubu_id(client)
    body = client.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": "rain_later"}).json()
    assert body["learning"]["mode"] == "rule_based"
    assert body["learning"]["ranker"] == "weighted-sum"
    top = body["courses"][0]
    assert top["safety"]["lighting_is_estimate"] is True
    assert top["safety_assessment"]["items"][0]["source"] == "demo"
    assert sum(group["contribution"] for group in top["score_breakdown"]) == pytest.approx(top["total_score"] + top["safety_assessment"]["penalty"], abs=0.1)


# ---------- 대체 경로
def _alternative(scenario="live", position=None, progress=0.0, now=FIXED_NOON, router=None):
    with SessionLocal() as db:
        pet = db.query(Pet).first()
        user = db.get(User, pet.user_id)
        course = db.query(WalkingCourse).order_by(WalkingCourse.id).first()
        return evaluate_alternative(db, pet, user, course, position, progress, scenario, now, router=router), course.start_lat, course.start_lng


def test_mild_weather_keeps_walking(client):
    result, _, _ = _alternative()
    assert result["status"] == "continue"
    assert result["action"] == "continue"
    assert result["alternatives"] == []
    assert result["return_route"] is None
    assert "실시간 강수 감지가 아니" in result["data_limit"]


def test_rain_starting_mid_walk_offers_a_return_route_and_shorter_options(client):
    result, lat, lng = _alternative("rain_now", position=(lat_near := 37.5525, 126.9040), progress=800)
    assert result["status"] == "shorten"
    assert result["action"] == "return_to_start"
    assert result["return_route"]["route"][-1] == [lat, lng]
    assert result["return_route"]["distance_m"] > 0
    assert result["weather"]["is_mock"] is True
    assert lat_near


def test_rain_ahead_during_the_remaining_walk_shortens(client, monkeypatch):
    rain_after_five = lambda t: {"precipitation_probability": 85.0, "precipitation_mm": 1.5} if t.hour >= 17 else {}  # noqa: E731

    def fake_weather(db, now, windows, scenario):
        return WeatherResult(make_forecast(now, rule=rain_after_five), "open-meteo", "live", False, None)

    monkeypatch.setattr("app.services.alternative_service.get_weather", fake_weather)
    # 비가 오기 전에 끝나면 계속 걷되, 예보를 알려 준다.
    early, _, _ = _alternative(position=(37.5525, 126.9040), now=datetime(2026, 10, 30, 15, 40))
    assert early["status"] == "continue"
    assert any("오후 5시부터 비 예보" in reason for reason in early["reasons"])
    # 남은 시간이 비 예보와 겹치면 줄이도록 안내한다.
    late, _, _ = _alternative(position=(37.5525, 126.9040), now=datetime(2026, 10, 30, 16, 50))
    assert late["status"] == "shorten"
    assert any("겹쳐요" in reason for reason in late["reasons"])
    assert late["return_route"]["route"]
    assert late["assessment"]["items"][0]["source"] == "forecast"


def test_heavy_rain_means_return_now(client):
    result, _, _ = _alternative("heavy_rain", position=(37.5525, 126.9040), progress=100)
    assert result["status"] == "return_now"
    assert any("비" in reason for reason in result["reasons"])


def test_finishing_is_suggested_when_it_is_shorter_than_going_back(client):
    with SessionLocal() as db:
        course = db.query(WalkingCourse).order_by(WalkingCourse.id).first()
        total = course.distance_km * 1000
        far_point = course.route[len(course.route) // 2]
    result, _, _ = _alternative("rain_now", position=tuple(far_point), progress=total - 30)
    assert result["action"] == "finish_course"


def test_no_location_gives_a_clear_message_and_no_route(client):
    result, _, _ = _alternative("rain_now", position=None, progress=500)
    assert result["status"] == "shorten"
    assert result["action"] == "no_location"
    assert result["return_route"] is None
    assert "위치 권한" in result["location_notice"]


def test_alternative_courses_avoid_rain_and_blocked_conditions(client):
    now = datetime(2026, 10, 30, 15, 0)
    result, _, _ = _alternative("rain_later", position=(37.5525, 126.9040), progress=0, now=now.replace(hour=16, minute=30))
    for option in result["alternatives"]:
        assert option["from_here_m"] <= 1500
        assert option["safety_level"] != "blocked"


def test_alternative_api(client):
    pet_id = dubu_id(client)
    course_id = client.get("/api/courses").json()[0]["id"]
    ok = client.post("/api/routes/alternative", json={"pet_id": pet_id, "course_id": course_id, "latitude": 37.55, "longitude": 126.9, "progress_m": 100, "weather_scenario": "rain_now"})
    assert ok.status_code == 200
    assert ok.json()["status"] == "shorten"
    no_gps = client.post("/api/routes/alternative", json={"pet_id": pet_id, "course_id": course_id, "weather_scenario": "rain_now"})
    assert no_gps.json()["action"] == "no_location"
    half = client.post("/api/routes/alternative", json={"pet_id": pet_id, "course_id": course_id, "latitude": 37.55})
    assert half.status_code == 422
    assert client.post("/api/routes/alternative", json={"pet_id": 999, "course_id": course_id}).status_code == 404
    assert client.post("/api/routes/alternative", json={"pet_id": pet_id, "course_id": 999}).status_code == 404


def test_walking_route_api(client):
    body = client.post("/api/routes/walking", json={"from_latitude": 37.55, "from_longitude": 126.90, "to_latitude": 37.551, "to_longitude": 126.90}).json()
    assert body["mode"] == "straight"
    assert body["route"][-1] == [37.551, 126.90]
    assert client.post("/api/routes/walking", json={"from_latitude": 99, "from_longitude": 126.9, "to_latitude": 37, "to_longitude": 126}).status_code == 422


# ---------- 리포트
def _walk(client, pet_id, course_id, started_at, duration=30, source="manual", distance=None, recommendation_id=None, rating=None):
    body = {"pet_id": pet_id, "course_id": course_id, "duration_min": duration, "started_at": started_at.isoformat(), "tracking_source": source, "recommendation_id": recommendation_id}
    if distance is not None:
        body["distance_km"] = distance
    walk = client.post("/api/walks", json=body).json()
    if rating:
        client.post("/api/feedback", json={"walk_id": walk["id"], **{**FIVE_STARS, "pet_rating": rating}})
    return walk


def test_report_counts_this_week_and_compares_with_last_week(client):
    pet_id = dubu_id(client)
    courses = client.get("/api/courses").json()
    today = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    monday = today - timedelta(days=today.weekday())
    _walk(client, pet_id, courses[0]["id"], monday, duration=20, distance=1.0, rating=5)
    _walk(client, pet_id, courses[0]["id"], monday + timedelta(hours=8), duration=40, distance=2.0, rating=3)
    _walk(client, pet_id, courses[1]["id"], monday - timedelta(days=3), duration=30, distance=1.5)

    report = client.get("/api/walks/report", params={"pet_id": pet_id}).json()
    assert report["summary"]["walk_count"] == 2
    assert report["summary"]["total_distance_km"] == 3.0
    assert report["summary"]["total_minutes"] == 60
    assert report["summary"]["average_minutes"] == 30
    assert report["summary"]["average_pet_rating"] == 4
    assert report["previous_week"]["walk_count"] == 1
    assert report["change"]["walk_count"] == {"difference": 1.0, "percent": 100}
    assert report["change"]["total_distance_km"]["difference"] == 1.5
    assert len(report["daily"]) == 7
    assert report["daily"][0]["walk_count"] == 2
    assert report["daily"][0]["weekday"] == "월"
    assert sum(day["walk_count"] for day in report["daily"]) == 2
    assert report["favorite_courses"][0]["course_id"] == courses[0]["id"]
    assert report["favorite_courses"][0]["visit_count"] == 2
    assert [point["pet_rating"] for point in report["satisfaction_trend"]] == [5, 3]

    last_week = client.get("/api/walks/report", params={"pet_id": pet_id, "week_offset": -1}).json()
    assert last_week["summary"]["walk_count"] == 1


def test_report_excludes_simulated_walks_and_says_so(client):
    pet_id = dubu_id(client)
    course = client.get("/api/courses").json()[0]
    now = datetime.now().replace(microsecond=0)
    _walk(client, pet_id, course["id"], now - timedelta(minutes=30), source="simulation", rating=5)
    _walk(client, pet_id, course["id"], now - timedelta(minutes=90), source="gps", distance=1.2, rating=4)

    report = client.get("/api/walks/report", params={"pet_id": pet_id}).json()
    assert report["summary"]["walk_count"] == 1
    assert report["summary"]["total_distance_km"] == 1.2
    assert report["simulated_walks_excluded"] == 1
    assert [point["pet_rating"] for point in report["satisfaction_trend"]] == [4]

    insights = client.get(f"/api/pets/{pet_id}/insights").json()
    assert insights["stats"]["walk_count"] == 1
    assert insights["stats"]["simulated_walk_count"] == 1
    assert insights["stats"]["average_pet_rating"] == 4

    walks = client.get("/api/walks", params={"pet_id": pet_id}).json()
    assert {walk["is_simulated"] for walk in walks} == {True, False}


def test_report_with_no_previous_week_has_no_percentage(client):
    pet_id = dubu_id(client)
    report = client.get("/api/walks/report", params={"pet_id": pet_id}).json()
    assert report["summary"]["walk_count"] == 0
    assert report["summary"]["average_minutes"] is None
    assert report["change"]["walk_count"]["percent"] is None
    assert client.get("/api/walks/report", params={"pet_id": 999}).status_code == 404
    assert client.get("/api/walks/report", params={"pet_id": pet_id, "week_offset": 1}).status_code == 422


def test_report_compares_recommended_and_chosen_courses(client):
    pet_id = dubu_id(client)
    recommendation = client.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": "rain_later"}).json()
    now = datetime.now().replace(microsecond=0)
    top = recommendation["courses"][0]
    second = recommendation["courses"][1]
    _walk(client, pet_id, top["course_id"], now - timedelta(minutes=30), recommendation_id=recommendation["id"])
    _walk(client, pet_id, second["course_id"], now - timedelta(minutes=60), recommendation_id=recommendation["id"])

    compared = client.get("/api/walks/report", params={"pet_id": pet_id}).json()["recommendation_vs_actual"]
    assert compared["followed_top_count"] == 1
    assert compared["in_top_three_count"] == 2
    assert {item["chosen_rank"] for item in compared["walks"]} == {1, 2}


def test_walk_records_actual_distance_and_old_clients_default_to_manual(client):
    pet_id = dubu_id(client)
    course = client.get("/api/courses").json()[0]
    old_style = client.post("/api/walks", json={"pet_id": pet_id, "course_id": course["id"], "duration_min": 10}).json()
    assert old_style["tracking_source"] == "manual"
    assert old_style["distance_km"] == course["distance_km"]
    early = client.post("/api/walks", json={"pet_id": pet_id, "course_id": course["id"], "duration_min": 10, "tracking_source": "gps", "distance_km": 0.4}).json()
    assert early["distance_km"] == 0.4
    assert client.post("/api/walks", json={"pet_id": pet_id, "course_id": course["id"], "duration_min": 10, "tracking_source": "teleport"}).status_code == 422


def test_seed_course_data_stays_valid_as_json():
    raw = json.loads(json.dumps([{"name": course.name} for course in COURSES]))
    assert len(raw) == len(COURSES)
    assert build_features(make_pet()).life_stage == "adult"
