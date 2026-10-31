"""추천 v2: 안전 단계, 5개 묶음 개인화, 최종 랭킹, 피드백 학습, 이력과 지표.

고도화 지시서 8단계의 검증 시나리오 14개를 test_scenario_XX로 둔다. 결과는 docs/RECOMMENDER.md에 정리한다.
"""
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import Pet, Recommendation, RecommendationEvent, RecommendationItem, WalkHistory
from app.recommender.config import GROUP_WEIGHTS, LEGACY_CONFIG, V1, V2
from app.recommender.diversity import route_overlap
from app.recommender.engine import MAX_SKIP_PENALTY, recommend
from app.recommender.evaluation import graded_relevance, hit_rate_at_k, ndcg_at_k, precision_at_k, recall_at_k
from app.recommender.features import build_features
from app.recommender.preference import apply_feedback, feedback_signal, record_visit
from app.recommender.profile import adjusted_ideal_km, build_profile
from app.recommender.safety import UNAVAILABLE, assess_course
from app.recommender.timeslots import evaluate_slot
from app.recommender.types import FeedbackInput, PreferenceState, Schedule, TimeWindow, WalkSample
from app.services.recommendation_service import load_behavior
from app.services.weather_providers import scenario_forecast
from tests.conftest import EMPTY_STATE, NOW, default_schedule, make_course, make_forecast, make_pet, seed_course_data
from tests.test_api_e2e import FIVE_STARS, PET_BODY, dubu_id
from tests.test_auth import signup

COURSES = seed_course_data()
GREAT = FeedbackInput(5, 5, "just_right", 5, True)
POOR = FeedbackInput(1, 1, "hard", 4, False)
SENIOR = make_pet(name="할배", size="large", weight_kg=28, age_years=11, activity_level="medium", personality="active", path_preference="new", novelty_reaction="calm")
ENERGETIC = make_pet(name="바람", size="large", weight_kg=28, activity_level="high", personality="active", path_preference="new", novelty_reaction="calm")
LAZY = make_pet(name="솜", size="small", weight_kg=4, activity_level="low", personality="timid", path_preference="familiar", novelty_reaction="calm")
TIER = {"good": 0, "caution": 0, "danger": 1}


def run(pet=None, courses=COURSES, forecast=None, schedule=None, state=EMPTY_STATE, now=NOW, **kwargs):
    return recommend(pet or make_pet(), courses, forecast if forecast is not None else make_forecast(now), schedule or default_schedule(), state, now, **kwargs)


def walked(state: PreferenceState, course, feedback: FeedbackInput, times: int = 1) -> PreferenceState:
    """산책과 피드백을 times번 남긴 상태. 서비스가 산책 기록에서 만드는 표본도 함께 넣는다."""
    walks = list(state.walks)
    for _ in range(times):
        state = apply_feedback(record_visit(state, course.id), course, feedback, 16)
        walks.append(WalkSample(course.id, course.distance_km, course.duration_min, course.duration_min, 16, "manual", feedback_signal(feedback), feedback.difficulty))
    return replace(state, walks=tuple(walks))


def by_id(result, course_id):
    return next((item for item in result.courses if item.course.id == course_id), None)


# ---------- 1. 신규 사용자
def test_scenario_01_new_user_uses_profile_and_rules_only():
    result = run()
    assert result.algorithm_version == V2 and result.status == "ok"
    assert result.weights["feedback"] == 0 and result.weights["user_preference"] == 0
    assert sum(result.weights[key] for key in ("pet_fit", "user_preference", "distance_time", "weather_env")) == pytest.approx(1.0, abs=1e-3)
    for item in result.courses:
        groups = {group.key: group for group in item.groups}
        assert not groups["feedback"].available and not groups["user_preference"].available
        assert item.total_score == item.baseline_score
        assert any("과거 선호도는 반영하지 않았어요" in basis["text"] for basis in item.explanation.basis)


def test_explicit_preferences_turn_on_the_user_preference_group():
    result = run(pet=make_pet(preferred_distance_km=2.0, preferred_time_bucket="evening"))
    assert result.weights["user_preference"] == pytest.approx(0.25 / 0.85, abs=1e-3)
    group = next(g for g in result.courses[0].groups if g.key == "user_preference")
    assert group.available and group.source == "보호자 입력"


# ---------- 2. 기존 사용자
def test_scenario_02_existing_user_gets_feedback_weight_that_grows_but_stays_bounded():
    target = COURSES[4]
    one = run(state=walked(EMPTY_STATE, target, GREAT))
    many = run(state=walked(EMPTY_STATE, target, GREAT, times=12))
    assert 0 < one.weights["feedback"] < many.weights["feedback"] <= GROUP_WEIGHTS["feedback"]
    entry = by_id(many, target.id)
    assert entry is not None and entry.total_score > entry.baseline_score
    assert any("피드백 12건" in basis["text"] for basis in entry.explanation.basis)


def test_feedback_does_not_drag_down_courses_without_feedback():
    """피드백 묶음을 가중합에 그대로 넣으면 중립값 50 때문에 모든 코스가 4~5점 내려가던 문제."""
    target = COURSES[2]
    before = run()
    after = run(state=walked(EMPTY_STATE, target, GREAT))
    for item in after.courses:
        if item.course.id != target.id:
            old = by_id(before, item.course.id)
            if old is not None:
                assert item.total_score >= old.total_score - 1.0


# ---------- 3~5. 반려견 특성
def test_scenario_03_low_activity_dog_gets_a_short_walk():
    lazy = run(pet=LAZY).courses[0].course
    energetic = run(pet=ENERGETIC).courses[0].course
    assert build_features(LAZY).ideal_distance_km < 1.5
    assert lazy.distance_km < energetic.distance_km


def test_scenario_04_high_activity_dog_gets_a_long_walk():
    result = run(pet=ENERGETIC, schedule=default_schedule(preferred_duration_min=60))
    assert build_features(ENERGETIC).ideal_distance_km > 4
    assert result.courses[0].course.distance_km >= 2.5


def test_scenario_05_senior_dog_gets_flat_and_shorter_courses():
    adult = replace(SENIOR, age_years=4)
    schedule = default_schedule(preferred_duration_min=120)
    senior_result = run(pet=SENIOR, schedule=schedule)
    assert build_features(SENIOR).life_stage == "senior"
    assert all(item.course.difficulty == "easy" for item in senior_result.courses)
    assert senior_result.courses[0].course.distance_km <= run(pet=adult, schedule=schedule).courses[0].course.distance_km
    assert "노령견" in senior_result.courses[0].explanation.basis[0]["text"]


# ---------- 6~7. 날씨
def test_scenario_06_heatwave_excludes_hot_hours_and_unshaded_long_courses():
    result = run(forecast=scenario_forecast("heatwave", NOW, NOW.replace(hour=16)))
    assert result.walkable and all(item.slot.start.hour >= 19 for item in result.courses)
    assert any("그늘" in reason for item in result.excluded for reason in item.reasons)


def test_scenario_06_cold_warns_about_the_cold_and_strongly_warns_on_danger():
    for pet in (make_pet(), SENIOR):
        result = run(pet=pet, forecast=scenario_forecast("cold", NOW, NOW.replace(hour=16)))
        assert result.walkable
        for item in result.courses:
            temperature = next(i for i in item.safety.items if i.key == "temperature")
            assert temperature.status in ("caution", "danger")
            if item.safety.level == "danger":
                assert item.safety.warning and "권하지 않아요" in item.safety.warning
                assert item.explanation.basis[0]["key"] == "warning"
            else:
                assert item.safety.warning is None


def test_scenario_07_heavy_rain_recommends_nothing_and_says_why():
    result = run(forecast=scenario_forecast("heavy_rain", NOW, NOW.replace(hour=16)))
    assert result.status == "unsafe" and not result.courses
    assert any("비" in reason for reason in result.blocked_reasons)
    assert result.indoor_alternatives


def test_scenario_07_rain_excludes_unpaved_courses():
    result = run(forecast=scenario_forecast("rain_now", NOW, NOW.replace(hour=16)))
    assert all(item.course.is_paved for item in result.courses)
    assert any("미끄러" in reason for item in result.excluded for reason in item.reasons)


# ---------- 8. 날씨 데이터 누락
def test_scenario_08_no_forecast_is_reported_as_missing_data_not_bad_weather():
    result = run(forecast=[])
    assert result.status == "no_forecast" and not result.walkable
    assert result.data_notice and "예보" in result.data_notice
    assert result.blocked_reasons == (result.data_notice,)


def test_scenario_08_weather_api_failure_does_not_claim_good_weather():
    result = run(weather_source=UNAVAILABLE)
    assert result.walkable and result.data_notice
    assert result.weights["weather_env"] == 0
    for item in result.courses:
        weather_items = [i for i in item.safety.items if i.key in ("temperature", "rain", "wind", "uv")]
        assert all(i.status == "unverified" and i.source == UNAVAILABLE for i in weather_items)
        assert item.safety.level != "good"
        assert "산책하기 좋아요" not in item.explanation.summary
        assert "날씨" in item.explanation.summary


def test_no_window_and_no_candidates_are_distinguished():
    assert run(schedule=Schedule((), 40, 1)).status == "no_window"
    assert run(courses=[make_course(1, pet_allowed=False)]).status == "no_candidates"


# ---------- 9. 안전 정보 누락
def test_scenario_09_missing_safety_data_is_never_called_good():
    unknown = frozenset({"shade_level", "traffic_exposure", "is_paved", "has_park", "crowd_level", "difficulty"})
    course = make_course(1, lighting="unknown", unknown=unknown, facility_counts={})
    slot = evaluate_slot(NOW.replace(hour=16), 25, TimeWindow(16, 20), {h.time: h for h in make_forecast()}, build_features(make_pet()), EMPTY_STATE, NOW)
    assessment = assess_course(course, slot, build_features(make_pet()))
    assert assessment.level != "good"
    assert assessment.data_quality["shares"]["missing"] >= 0.25 and assessment.data_quality["insufficient"]
    assert {"조명", "그늘", "차량 노출", "노면"} <= set(assessment.data_quality["missing_items"])


def test_air_quality_without_data_is_listed_as_unverified_and_not_scored():
    item = next(i for i in run().courses[0].safety.items if i.key == "air")
    assert item.status == "unverified" and item.score is None and item.source == "unknown"


def test_air_quality_uses_the_environment_ministry_grades():
    from app.recommender.safety import air_quality_item
    from tests.conftest import make_hour

    assert air_quality_item(make_hour(NOW, pm10=40, pm2_5=20), "forecast").status == "ok"
    assert air_quality_item(make_hour(NOW, pm10=90), "forecast").status == "caution"
    assert air_quality_item(make_hour(NOW, pm2_5=80), "forecast").status == "danger"


def test_danger_courses_never_rank_above_safer_ones():
    night = Schedule((TimeWindow(20, 23),), 40, 1)
    risky = make_course(1, name="큰길", environment={"road": {"pedestrian": 0.1, "local": 0.2, "major": 0.7, "unknown": 0.0}})
    safe = make_course(2, name="골목", crowd_level="medium", has_park=False, is_familiar=False, environment={"road": {"pedestrian": 0.6, "local": 0.4, "major": 0.0, "unknown": 0.0}})
    result = run(courses=[risky, safe], schedule=night)
    levels = [item.safety.level for item in result.courses]
    assert levels[0] != "danger" and "danger" in levels
    # 같은 조건의 v1은 개인화 점수가 높은 위험 코스를 먼저 올렸다.
    assert run(courses=[risky, safe], schedule=night, config=LEGACY_CONFIG).courses[0].course.id == risky.id


@pytest.mark.parametrize("weather", ["mild", "rain_later", "rain_now", "heatwave", "cold"])
def test_safety_tier_is_monotonic_for_every_seed_condition(weather):
    forecast = make_forecast() if weather == "mild" else scenario_forecast(weather, NOW, NOW.replace(hour=16))
    for pet in (make_pet(), ENERGETIC, SENIOR, LAZY):
        tiers = [TIER[item.safety.level] for item in run(pet=pet, forecast=forecast).courses]
        assert tiers == sorted(tiers)


# ---------- 10. 코스 데이터 부족
def test_scenario_10_fewer_than_three_candidates_are_not_padded():
    result = run(courses=COURSES[:2])
    assert len(result.courses) == 2
    assert {item.course.id for item in result.courses} <= {course.id for course in COURSES[:2]}


def test_duplicate_route_is_used_only_when_nothing_else_is_left():
    route = ((37.55, 126.90), (37.551, 126.901), (37.552, 126.902))
    a = make_course(1, route=route)
    b = make_course(2, route=route, crowd_level="medium")
    result = run(courses=[a, b])
    assert len(result.courses) == 2
    assert result.courses[1].similar_to == a.name
    assert any("겹쳐요" in caution for caution in result.courses[1].explanation.other_cautions)


# ---------- 11~12. 만족도와 순위
def test_scenario_11_liked_course_is_recommended_again_with_a_higher_score():
    first = run()
    target = first.courses[1].course
    after = run(state=walked(EMPTY_STATE, target, GREAT))
    entry = by_id(after, target.id)
    assert entry is not None
    assert entry.total_score > first.courses[1].total_score
    assert entry.rank <= 2
    assert "지난번 만족도가 높았던" in entry.explanation.summary
    # 두 번째 5점이면 1위로 오른다.
    assert run(state=walked(EMPTY_STATE, target, GREAT, times=2)).courses[0].course.id == target.id


def test_scenario_12_disliked_course_drops_out_of_first_place():
    target = run().courses[0].course
    once = run(state=walked(EMPTY_STATE, target, POOR))
    twice = run(state=walked(EMPTY_STATE, target, POOR, times=2))
    assert by_id(once, target.id) is None or by_id(once, target.id).total_score < run().courses[0].total_score
    assert twice.courses[0].course.id != target.id


def test_one_rating_does_not_swing_the_ranking_by_more_than_the_feedback_cap():
    target = COURSES[9]
    before = run(pet=ENERGETIC)
    after = run(pet=ENERGETIC, state=walked(EMPTY_STATE, target, GREAT))
    entry = next(item for item in after.candidates if item.course_id == target.id)
    old = next(item for item in before.candidates if item.course_id == target.id)
    assert entry.total_score - old.total_score <= GROUP_WEIGHTS["feedback"] * 100


# ---------- 13. 일관성
def test_scenario_13_same_input_gives_the_same_ranking():
    first = [(i.course.id, i.total_score) for i in run().courses]
    assert all(first == [(i.course.id, i.total_score) for i in run().courses] for _ in range(3))


@pytest.mark.parametrize("minute", [0, 30, 90, 150])
def test_scenario_13_calling_later_in_the_morning_keeps_the_ranking(minute):
    forecast = make_forecast()
    later = NOW + timedelta(minutes=minute)
    assert [i.course.id for i in run(forecast=forecast, now=later).courses] == [i.course.id for i in run(forecast=forecast).courses]


# ---------- 14. 편중
def test_scenario_14_overlapping_seed_routes_never_appear_together():
    seoulham = next(c for c in COURSES if c.name == "서울함공원 강변 왕복")
    hangang = next(c for c in COURSES if c.name == "한강 강변 종주 코스")
    assert route_overlap(seoulham.route, hangang.route) >= 0.6
    for pet in (make_pet(), ENERGETIC, SENIOR, LAZY, make_pet(path_preference="new", novelty_reaction="calm")):
        for schedule in (default_schedule(), default_schedule(preferred_duration_min=70)):
            ids = {item.course.id for item in run(pet=pet, schedule=schedule).courses}
            assert not {seoulham.id, hangang.id} <= ids


def test_scenario_14_a_new_course_replaces_the_third_when_all_were_visited():
    state = EMPTY_STATE
    for item in run().courses:
        state = walked(state, item.course, FeedbackInput(3, 3, "just_right", 4, False))
    result = run(state=state)
    assert sum(item.exploration for item in result.courses) <= 1
    if any(item.exploration for item in result.courses):
        explored = next(item for item in result.courses if item.exploration)
        assert explored.rank == 3 and state.courses.get(explored.course.id) is None
        assert "안 가 본 코스" in explored.explanation.summary


def test_skipped_days_lower_the_score_a_little_and_are_capped():
    top = run().courses[0]
    state = replace(EMPTY_STATE, skipped_days={top.course.id: 9})
    entry = next(item for item in run(state=state).candidates if item.course_id == top.course.id)
    assert entry.skip_penalty == MAX_SKIP_PENALTY
    assert entry.total_score == pytest.approx(top.total_score - MAX_SKIP_PENALTY, abs=0.01)


# ---------- 학습 프로필
def test_profile_needs_enough_evidence_and_ignores_simulated_walks():
    sample = WalkSample(1, 2.0, 30, 30, 16, "manual", 90.0, "just_right")
    assert build_profile((sample,)).preferred_distance_km is None
    assert build_profile((sample, sample)).preferred_distance_km == 2.0
    simulated = replace(sample, tracking_source="simulation")
    assert build_profile((simulated,) * 5).preferred_distance_km is None


def test_profile_shrinks_distance_after_hard_walks_and_reads_pace_from_gps_only():
    hard = WalkSample(1, 3.0, 40, 60, 16, "gps", 70.0, "hard")
    profile = build_profile((hard, hard))
    assert profile.preferred_distance_km == pytest.approx(2.4)
    assert profile.pace_ratio == 1.5
    manual = replace(hard, tracking_source="manual")
    assert build_profile((manual, manual)).pace_ratio is None


def test_learned_distance_only_nudges_the_ideal_distance():
    profile = build_profile((WalkSample(1, 1.0, 20, 20, 16, "manual", 90.0, "just_right"),) * 2)
    ideal, share = adjusted_ideal_km(3.0, profile)
    assert share == pytest.approx(1 / 3, abs=1e-3)
    assert ideal == pytest.approx(3.0 * 2 / 3 + 1.0 / 3, abs=0.01)


# ---------- v1 유지와 기록
def test_legacy_version_is_still_available():
    result = run(config=LEGACY_CONFIG)
    assert result.algorithm_version == V1
    assert sum(result.weights.values()) == pytest.approx(1.1)


def test_every_candidate_is_logged_with_its_scores():
    result = run(forecast=scenario_forecast("heatwave", NOW, NOW.replace(hour=16)))
    logged = {item.course_id: item for item in result.candidates}
    assert set(logged) == {course.id for course in COURSES}
    assert sorted(item.rank for item in logged.values() if item.rank) == list(range(1, len(result.courses) + 1))
    excluded = [item for item in logged.values() if item.excluded_reasons]
    assert excluded and all(item.total_score is None for item in excluded)
    ranked = next(item for item in logged.values() if item.rank == 1)
    assert set(ranked.groups) == set(GROUP_WEIGHTS)


# ---------- 평가 지표
def test_ranking_metrics_match_hand_computed_values():
    ranked = [3, 1, 2]
    assert precision_at_k(ranked, {1, 9}) == pytest.approx(1 / 3)
    assert recall_at_k(ranked, {1, 9}) == 0.5
    assert recall_at_k(ranked, set()) is None
    assert hit_rate_at_k(ranked, {9}) == 0
    assert ndcg_at_k(ranked, {1: 1.0}) == pytest.approx(1 / 1.5849625, abs=1e-6)
    assert ndcg_at_k(ranked, {3: 1.0}) == 1.0
    assert graded_relevance(5) == 1 and graded_relevance(1) == 0


# ---------- API, DB
def test_recommendation_stores_version_weather_time_and_every_candidate(client):
    pet_id = dubu_id(client)
    body = client.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": "heatwave"}).json()
    assert body["algorithm"]["version"] == V2 and body["status"] == "ok"
    with SessionLocal() as db:
        record = db.get(Recommendation, body["id"])
        assert record.algorithm_version == V2 and record.weather_fetched_at is not None
        items = list(db.scalars(select(RecommendationItem).where(RecommendationItem.recommendation_id == record.id)))
    assert len(items) == len(client.get("/api/courses").json())
    assert [i.course_id for i in sorted((i for i in items if i.rank), key=lambda i: i.rank)] == [c["course_id"] for c in body["courses"]]
    assert any(i.excluded_reasons for i in items)
    candidates = client.get(f"/api/recommendations/{body['id']}/candidates").json()
    assert {c["course_id"] for c in candidates} == {i.course_id for i in items}


def test_events_are_recorded_once_and_only_for_recommended_courses(client):
    pet_id = dubu_id(client)
    body = client.post("/api/recommendations", json={"pet_id": pet_id}).json()
    course_id = body["courses"][0]["course_id"]
    url = f"/api/recommendations/{body['id']}/events"
    assert client.post(url, json={"course_id": course_id, "event": "select"}).status_code == 204
    assert client.post(url, json={"course_id": course_id, "event": "select"}).status_code == 204
    assert client.post(url, json={"course_id": course_id, "event": "start"}).status_code == 204
    outside = next(c["id"] for c in client.get("/api/courses").json() if c["id"] not in {x["course_id"] for x in body["courses"]})
    assert client.post(url, json={"course_id": outside, "event": "start"}).status_code == 422
    assert client.post(url, json={"course_id": course_id, "event": "click"}).status_code == 422
    with SessionLocal() as db:
        assert len(list(db.scalars(select(RecommendationEvent)))) == 2


def test_other_accounts_cannot_log_events_or_read_metrics(client):
    pet_id = dubu_id(client)
    body = client.post("/api/recommendations", json={"pet_id": pet_id}).json()
    signup(client, login_id="stranger")
    assert client.post(f"/api/recommendations/{body['id']}/events", json={"course_id": body["courses"][0]["course_id"], "event": "start"}).status_code == 404
    assert client.get(f"/api/recommendations/{body['id']}/candidates").status_code == 404
    assert client.get(f"/api/pets/{pet_id}/recommendation-metrics").status_code == 404


def test_signed_in_users_do_not_inherit_the_demo_neighborhood_assumption(client):
    """시드 코스의 '집 근처' 표시는 시연 보호자 기준이다. 다른 보호자에게 '익숙한 코스'라고 하지 않는다."""
    signup(client, login_id="newbie")
    pet = client.post("/api/pets", json={**PET_BODY, "personality": "timid", "path_preference": "familiar", "novelty_reaction": "anxious"}).json()
    body = client.post("/api/recommendations", json={"pet_id": pet["id"], "weather_scenario": "rain_later"}).json()
    assert body["courses"]
    assert all("익숙한" not in course["reason"]["summary"] for course in body["courses"])


def test_online_metrics_separate_real_and_demo_data_and_flag_small_samples(client):
    from app.clock import now_local
    from app.services.recommendation_metrics import service_metrics

    pet_id = dubu_id(client)
    body = client.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": "rain_later"}).json()
    top = body["courses"][0]
    client.post(f"/api/recommendations/{body['id']}/events", json={"course_id": top["course_id"], "event": "start"})
    walk = client.post("/api/walks", json={"pet_id": pet_id, "course_id": top["course_id"], "duration_min": top["duration_min"], "recommendation_id": body["id"]}).json()
    client.post("/api/feedback", json={"walk_id": walk["id"], **FIVE_STARS})
    client.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": "rain_later"})

    metrics = client.get(f"/api/pets/{pet_id}/recommendation-metrics").json()["all"]
    assert metrics["walkable_recommendations"] == 2 and metrics["reliable"] is False
    assert metrics["ranking"]["reliable"] is False and metrics["quality"]["reliable"] is False
    assert metrics["quality"]["selection_rate"] == 0.5 and metrics["quality"]["start_rate"] == 0.5
    assert metrics["quality"]["completion_rate"] == 0.5 and metrics["quality"]["average_pet_rating"] == 5
    assert metrics["ranking"]["hit_rate_at_3"] == 1.0 and metrics["ranking"]["ndcg_at_3"] == 1.0
    assert metrics["quality"]["save_rate"] is None and metrics["not_measured"]["save_rate"]

    with SessionLocal() as db:
        report = service_metrics(db, now_local())
    assert report["segments"]["demo"]["all"]["walkable_recommendations"] == 2
    assert report["segments"]["user"]["all"]["walkable_recommendations"] == 0


def test_simulated_walks_are_left_out_of_behavior_metrics(client):
    pet_id = dubu_id(client)
    body = client.post("/api/recommendations", json={"pet_id": pet_id}).json()
    top = body["courses"][0]
    client.post("/api/walks", json={"pet_id": pet_id, "course_id": top["course_id"], "duration_min": 10, "recommendation_id": body["id"], "tracking_source": "simulation"})
    metrics = client.get(f"/api/pets/{pet_id}/recommendation-metrics").json()["all"]
    assert metrics["quality"]["completion_rate"] == 0


def test_skipped_days_count_only_days_when_another_course_was_walked(client):
    pet_id = dubu_id(client)
    shown = client.post("/api/recommendations", json={"pet_id": pet_id}).json()
    quiet = client.post("/api/recommendations", json={"pet_id": pet_id}).json()
    shown_ids = [c["course_id"] for c in shown["courses"]]
    other = next(c["id"] for c in client.get("/api/courses").json() if c["id"] not in shown_ids)
    now = datetime.now().replace(microsecond=0)
    yesterday = now - timedelta(days=1)
    with SessionLocal() as db:
        db.get(Recommendation, shown["id"]).created_at = yesterday
        # 사흘 전에는 추천만 보고 아무 데도 가지 않았다. 이 날은 세지 않는다.
        db.get(Recommendation, quiet["id"]).created_at = now - timedelta(days=3)
        db.add(WalkHistory(pet_id=pet_id, course_id=other, started_at=yesterday, ended_at=yesterday + timedelta(minutes=20), duration_min=20, tracking_source="manual", created_at=yesterday))
        db.commit()
        _, skipped = load_behavior(db, db.get(Pet, pet_id), now)
    assert skipped == {course_id: 1 for course_id in shown_ids}


def test_old_recommendations_without_tracking_are_not_counted_as_not_selected(client):
    pet_id = dubu_id(client)
    body = client.post("/api/recommendations", json={"pet_id": pet_id}).json()
    with SessionLocal() as db:
        db.get(Recommendation, body["id"]).algorithm_version = None
        db.commit()
    metrics = client.get(f"/api/pets/{pet_id}/recommendation-metrics").json()["all"]
    assert metrics["quality"]["tracked_recommendations"] == 0
    assert metrics["quality"]["selection_rate"] is None and metrics["quality"]["start_rate"] is None
    assert metrics["quality"]["completion_rate"] == 0


def test_top_n_can_return_every_candidate_for_route_generation():
    """산책길 만들기가 후보 전부의 순서를 받을 때 쓴다."""
    result = run(top_n=len(COURSES))
    assert len(result.courses) >= len(COURSES) - 1
    assert run(top_n=1).courses[0].course.id == result.courses[0].course.id
    assert len(run(top_n=1).courses) == 1
    assert len(run(config=LEGACY_CONFIG, top_n=5).courses) == 5


def test_weather_api_failure_flows_through_the_api_without_llm_or_good_weather_claims(client, monkeypatch):
    from app.services import recommendation_service
    from app.services.llm_service import enhance_recommendation
    from app.services.weather_providers import MockWeatherProvider
    from app.services.weather_service import FALLBACK_NOTICE, MOCK_FALLBACK, WeatherResult

    class MustNotBeCalled:
        name = "ollama"
        model = "x"

        def complete(self, system, user, schema):
            raise AssertionError("날씨를 모르는 추천에 LLM을 부르면 안 된다")

    def failed_weather(db, now, windows, scenario="live"):
        return WeatherResult(MockWeatherProvider().fetch(0, 0, now), MOCK_FALLBACK, "live", True, FALLBACK_NOTICE, now)

    monkeypatch.setattr(recommendation_service, "get_weather", failed_weather)
    pet_id = dubu_id(client)
    body = client.post("/api/recommendations", json={"pet_id": pet_id}).json()
    assert body["weather"]["is_available"] is False and body["data_notice"]
    assert body["explanation_engine"]["status"] == "disabled"
    assert body["weights"]["weather_env"] == 0
    for course in body["courses"]:
        assert course["safety_assessment"]["level"] != "good"
        assert "산책하기 좋아요" not in course["reason"]["summary"]
        assert not any("°C" in caution for caution in course["cautions"])
    with SessionLocal() as db:
        record = db.get(Recommendation, body["id"])
        assert enhance_recommendation(db, record, db.get(Pet, pet_id), MustNotBeCalled()) is record
