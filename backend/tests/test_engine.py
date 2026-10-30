from datetime import datetime, timedelta

import pytest

from app.recommender.engine import _rank_courses, recommend
from app.recommender.features import build_features
from app.recommender.preference import apply_feedback, record_visit
from app.recommender.types import FeedbackInput, PreferenceState
from app.services.weather_providers import scenario_forecast
from tests.conftest import (
    EMPTY_STATE,
    NOW,
    default_schedule,
    make_course,
    make_forecast,
    make_pet,
    seed_course_data,
)

COURSES = seed_course_data()
EXPECTED_SENTENCE = "낯선 길을 싫어하는 두부를 위해 익숙한 공원 코스를 골랐어요. 비가 오기 전 짧게 다녀올 수 있어요."
GREAT = FeedbackInput(5, 5, "just_right", 5, True)
POOR = FeedbackInput(1, 1, "hard", 4, False)


def run(pet=None, courses=COURSES, forecast=None, schedule=None, state=EMPTY_STATE, now=NOW):
    return recommend(
        pet=pet or make_pet(),
        courses=courses,
        forecast_hours=forecast if forecast is not None else make_forecast(now),
        schedule=schedule or default_schedule(),
        state=state,
        now=now,
    )


def test_returns_three_ranked_courses_in_score_order():
    result = run()
    assert result.walkable is True
    assert [item.rank for item in result.courses] == [1, 2, 3]
    scores = [item.total_score for item in result.courses]
    assert scores == sorted(scores, reverse=True)


def test_dubu_gets_a_quiet_familiar_park_course_first():
    top = run().courses[0].course
    assert top.is_familiar and top.has_park and top.crowd_level == "low"


def test_a_crowded_course_ranks_lower_for_a_timid_pet_than_for_an_active_one():
    crowded = next(c for c in COURSES if c.crowd_level == "high")
    def rank_of(pet):
        forecast = {hour.time: hour for hour in make_forecast()}
        ranked = _rank_courses(COURSES, NOW, forecast, pet, build_features(pet), default_schedule(), EMPTY_STATE)
        return [item[0].id for item in ranked].index(crowded.id)
    timid = rank_of(make_pet())
    active = rank_of(make_pet(size="large", weight_kg=28, activity_level="high", personality="active", path_preference="new", novelty_reaction="calm"))
    assert active < timid


def test_recommendations_differ_between_very_different_pets():
    timid = run().courses
    explorer = run(pet=make_pet(name="바람", size="large", weight_kg=30, activity_level="high", personality="active", path_preference="new", novelty_reaction="calm")).courses
    assert [i.course.id for i in timid] != [i.course.id for i in explorer]
    assert explorer[0].course.distance_km > timid[0].course.distance_km


@pytest.mark.parametrize("hour,minute", [(0, 5), (7, 30), (10, 0), (15, 59), (16, 0), (16, 30), (18, 45), (19, 30), (20, 0), (23, 50)])
def test_rain_scenario_yields_the_exact_sentence_at_any_time_of_day(hour, minute):
    now = datetime(2026, 10, 30, hour, minute)
    first = now if now.minute == 0 else now.replace(minute=0) + timedelta(hours=1)
    anchor = next(first + timedelta(hours=i) for i in range(24) if 16 <= (first + timedelta(hours=i)).hour < 20)
    result = run(forecast=scenario_forecast("rain_later", now, anchor), now=now)
    assert result.courses[0].explanation.summary == EXPECTED_SENTENCE
    assert result.courses[0].slot.start == anchor


def test_rain_scenario_pushes_long_courses_out_of_the_top():
    forecast = scenario_forecast("rain_later", NOW, NOW.replace(hour=16))
    top = run(forecast=forecast).courses
    assert all(item.slot.rain_overlap_min == 0 for item in top[:1])
    assert top[0].course.duration_min <= 30


def test_heavy_rain_returns_no_course_and_an_indoor_alternative():
    forecast = scenario_forecast("heavy_rain", NOW, NOW.replace(hour=16))
    result = run(forecast=forecast)
    assert result.walkable is False
    assert result.courses == ()
    assert result.indoor_alternatives
    assert any("비" in reason for reason in result.blocked_reasons)


def test_heatwave_only_allows_the_cooler_hour():
    forecast = scenario_forecast("heatwave", NOW, NOW.replace(hour=16))
    result = run(forecast=forecast)
    assert result.walkable is True
    assert all(item.slot.start.hour >= 19 for item in result.courses)
    assert any(slot.unsafe_reason for slot in result.time.all_slots)


def test_cold_weather_prefers_shorter_courses_than_mild_weather():
    mild = run().courses[0].course.distance_km
    cold = run(forecast=scenario_forecast("cold", NOW, NOW.replace(hour=16))).courses[0].course.distance_km
    assert cold <= mild


def test_courses_that_do_not_allow_pets_are_never_recommended():
    banned = make_course(1, pet_allowed=False)
    allowed = make_course(2, crowd_level="high")
    result = run(courses=[banned, allowed])
    assert [item.course.id for item in result.courses] == [2]


def test_five_star_feedback_raises_the_course_in_the_next_recommendation():
    first = run()
    target = first.courses[2]
    state = apply_feedback(record_visit(EMPTY_STATE, target.course.id), target.course, GREAT, 16)
    second = run(state=state)
    updated = next(item for item in second.courses if item.course.id == target.course.id)
    assert updated.total_score > target.total_score
    assert updated.total_score > updated.baseline_score
    assert updated.rank <= target.rank


def test_repeated_good_feedback_changes_the_ranking():
    baseline = run()
    # 기준선 상위권 밖의 코스를 골라 반복해서 좋은 피드백을 준다.
    all_ids = {c.id: c for c in COURSES}
    top_ids = {item.course.id for item in baseline.courses}
    target = next(c for c in COURSES if c.id not in top_ids and c.crowd_level != "high")
    state = PreferenceState()
    for _ in range(6):
        state = apply_feedback(record_visit(state, target.id), all_ids[target.id], GREAT, 16)
    result = run(state=state)
    assert target.id in {item.course.id for item in result.courses}
    entry = next(item for item in result.courses if item.course.id == target.id)
    assert entry.baseline_rank > entry.rank


def test_repeated_poor_feedback_drops_the_top_course():
    baseline = run()
    target = baseline.courses[0].course
    state = PreferenceState()
    for _ in range(4):
        state = apply_feedback(record_visit(state, target.id), target, POOR, 16)
    result = run(state=state)
    assert result.courses[0].course.id != target.id


def test_learning_delta_is_zero_without_feedback():
    for item in run().courses:
        assert item.total_score == item.baseline_score
        assert item.rank == item.baseline_rank


def test_engine_is_deterministic():
    first = run()
    second = run()
    assert [(i.course.id, i.total_score) for i in first.courses] == [(i.course.id, i.total_score) for i in second.courses]


def test_each_course_gets_a_time_inside_the_guardian_window():
    for item in run().courses:
        assert 16 <= item.slot.start.hour < 20


def test_reason_summary_is_personal_for_every_top_course():
    for item in run().courses:
        assert "두부" in item.explanation.summary
