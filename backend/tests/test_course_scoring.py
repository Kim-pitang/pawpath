import pytest

from app.recommender.course_scoring import (
    INITIAL_WEIGHTS,
    adaptive_weights,
    score_activity,
    score_course,
    score_personality,
    score_safety,
    score_schedule,
    score_weather,
)
from app.recommender.features import build_features
from app.recommender.preference import apply_feedback, record_visit
from app.recommender.timeslots import evaluate_slot
from app.recommender.types import FeedbackInput, PreferenceState, TimeWindow
from tests.conftest import (
    EMPTY_STATE,
    NOW,
    default_schedule,
    make_course,
    make_forecast,
    make_pet,
    seed_course_data,
)

PET = make_pet()
FEATURES = build_features(PET)
WINDOW = TimeWindow(16, 20)


def slot_at(hour=16, duration=25, rule=None, window=WINDOW, features=FEATURES):
    rows = {row.time: row for row in make_forecast(rule=rule)}
    return evaluate_slot(NOW.replace(hour=hour), duration, window, rows, features, EMPTY_STATE, NOW)


def test_initial_weights_match_the_specification_exactly():
    assert INITIAL_WEIGHTS == {
        "weather": 0.25,
        "personality": 0.25,
        "activity": 0.15,
        "schedule": 0.15,
        "safety": 0.10,
        "preference": 0.10,
    }
    assert adaptive_weights(0) == pytest.approx(INITIAL_WEIGHTS)


@pytest.mark.parametrize("feedback_total", [1, 4, 20, 1000])
def test_feedback_only_strengthens_the_preference_factor(feedback_total):
    weights = adaptive_weights(feedback_total)
    assert weights["preference"] > INITIAL_WEIGHTS["preference"]
    assert {k: v for k, v in weights.items() if k != "preference"} == {
        k: v for k, v in INITIAL_WEIGHTS.items() if k != "preference"
    }


def test_preference_weight_grows_with_feedback_but_stays_bounded():
    assert adaptive_weights(4)["preference"] > adaptive_weights(1)["preference"] > 0.10
    assert adaptive_weights(1000)["preference"] < 0.31


def test_total_is_the_weighted_sum_of_factors():
    total, factors, _ = score_course(make_course(), slot_at(), PET, FEATURES, default_schedule(), EMPTY_STATE)
    assert total == pytest.approx(sum(f.contribution for f in factors), abs=0.1)
    assert total == pytest.approx(sum(f.score * f.weight for f in factors), abs=0.1)


def test_all_factors_are_normalized_for_every_seed_course():
    extreme = lambda t: {"apparent_temperature": 31, "precipitation_probability": 90, "precipitation_mm": 2.5, "wind_speed": 12, "uv_index": 11}
    for course in seed_course_data():
        for rule in (None, extreme):
            slot = slot_at(duration=course.duration_min, rule=rule)
            total, factors, _ = score_course(course, slot, PET, FEATURES, default_schedule(), EMPTY_STATE)
            assert 0 <= total <= 100
            assert len(factors) == 6
            assert all(0 <= f.score <= 100 for f in factors)


def test_preference_is_neutral_without_feedback():
    _, factors, preference = score_course(make_course(), slot_at(), PET, FEATURES, default_schedule(), EMPTY_STATE)
    assert preference == 50.0
    assert next(f for f in factors if f.key == "preference").score == 50.0


def test_timid_pet_prefers_a_quiet_familiar_course():
    quiet, _ = score_personality(make_course(crowd_level="low"), PET, FEATURES, EMPTY_STATE)
    crowded, _ = score_personality(make_course(crowd_level="high", is_familiar=False), PET, FEATURES, EMPTY_STATE)
    assert quiet - crowded > 30


def test_new_path_lover_prefers_an_unvisited_course():
    pet = make_pet(path_preference="new", personality="curious", novelty_reaction="calm")
    features = build_features(pet)
    unknown, _ = score_personality(make_course(is_familiar=False), pet, features, EMPTY_STATE)
    state = record_visit(record_visit(record_visit(EMPTY_STATE, 1), 1), 1)
    visited, _ = score_personality(make_course(is_familiar=False), pet, features, state)
    assert unknown > visited


def test_visits_make_a_course_familiar_for_a_cautious_pet():
    course = make_course(is_familiar=False)
    before, _ = score_personality(course, PET, FEATURES, EMPTY_STATE)
    after, _ = score_personality(course, PET, FEATURES, record_visit(record_visit(EMPTY_STATE, 1), 1))
    assert after > before


def test_visits_do_not_make_a_disliked_course_feel_familiar():
    course = make_course()
    poor = FeedbackInput(1, 1, "hard", 5, False)
    state = EMPTY_STATE
    for _ in range(4):
        state = apply_feedback(record_visit(state, course.id), course, poor, 16)
    before, _ = score_personality(course, PET, FEATURES, EMPTY_STATE)
    after, evidence = score_personality(course, PET, FEATURES, state)
    assert after < before
    assert "지난 피드백이 낮았던 코스" in evidence


def test_activity_fit_peaks_near_the_ideal_distance():
    slot = slot_at()
    ideal, _ = score_activity(make_course(distance_km=FEATURES.ideal_distance_km), FEATURES, slot)
    long, _ = score_activity(make_course(distance_km=5.0), FEATURES, slot)
    short, _ = score_activity(make_course(distance_km=0.4), FEATURES, slot)
    assert ideal == pytest.approx(100)
    assert long < 40
    assert short < 40


def test_hill_penalizes_seniors_more():
    senior_pet = make_pet(age_years=12)
    senior = build_features(senior_pet)
    slot = slot_at(features=senior)
    flat, _ = score_activity(make_course(distance_km=1.0), senior, slot)
    hill, _ = score_activity(make_course(distance_km=1.0, difficulty="hard"), senior, slot)
    assert hill < flat * 0.8


def test_cold_weather_favors_a_shorter_course():
    cold = slot_at(rule=lambda t: {"apparent_temperature": 0.0})
    assert cold.ideal_factor < 1
    short, _ = score_activity(make_course(distance_km=1.0), FEATURES, cold)
    long, _ = score_activity(make_course(distance_km=1.8), FEATURES, cold)
    assert short > long


def test_schedule_fit_penalizes_courses_longer_than_the_guardian_can_walk():
    slot = slot_at()
    fits, _ = score_schedule(make_course(duration_min=35), slot, default_schedule())
    long, _ = score_schedule(make_course(duration_min=70), slot, default_schedule())
    assert fits == 100
    assert long < 25


def test_schedule_fit_penalizes_running_past_the_window():
    inside, _ = score_schedule(make_course(duration_min=40), slot_at(hour=17, duration=40), default_schedule())
    outside, evidence = score_schedule(make_course(duration_min=40), slot_at(hour=19, duration=90), default_schedule())
    assert outside < inside
    assert any("20시" in line for line in evidence)


def test_shade_helps_on_a_hot_day():
    hot = slot_at(rule=lambda t: {"apparent_temperature": 28.0})
    shady, _ = score_weather(make_course(shade_level=0.9), hot, FEATURES)
    open_course, _ = score_weather(make_course(shade_level=0.1), hot, FEATURES)
    assert shady > open_course


def test_unpaved_course_loses_points_when_wet():
    wet = slot_at(rule=lambda t: {"precipitation_probability": 70, "precipitation_mm": 1.0})
    paved, _ = score_weather(make_course(is_paved=True), wet, FEATURES)
    unpaved, _ = score_weather(make_course(is_paved=False), wet, FEATURES)
    assert paved > unpaved


def test_rain_overlap_lowers_the_weather_score():
    rule = lambda t: {"precipitation_probability": 85, "precipitation_mm": 1.5} if t.hour >= 17 else {}
    short, _ = score_weather(make_course(duration_min=25), slot_at(duration=25, rule=rule), FEATURES)
    long, _ = score_weather(make_course(duration_min=90), slot_at(duration=90, rule=rule), FEATURES)
    assert short > long + 20


def test_lighting_matters_much_more_after_dark():
    bright = make_course(lighting="good")
    dim = make_course(lighting="poor")
    day_gap = score_safety(bright, slot_at(hour=16))[0] - score_safety(dim, slot_at(hour=16))[0]
    night_gap = score_safety(bright, slot_at(hour=19))[0] - score_safety(dim, slot_at(hour=19))[0]
    assert night_gap > day_gap * 2


def test_verified_facilities_raise_the_safety_score():
    without, _ = score_safety(make_course(), slot_at())
    with_toilets, _ = score_safety(make_course(facility_counts={"toilets": 3}), slot_at())
    assert with_toilets > without


def test_five_stars_never_lower_and_one_star_never_raises_any_course():
    great = FeedbackInput(5, 5, "just_right", 5, True)
    poor = FeedbackInput(1, 1, "hard", 5, False)
    for course in seed_course_data():
        slot = slot_at(duration=course.duration_min)
        base, _, _ = score_course(course, slot, PET, FEATURES, default_schedule(), EMPTY_STATE)
        up_state, down_state = EMPTY_STATE, EMPTY_STATE
        for count in range(1, 6):
            up_state = apply_feedback(record_visit(up_state, course.id), course, great, 16)
            down_state = apply_feedback(record_visit(down_state, course.id), course, poor, 16)
            up, _, _ = score_course(course, slot, PET, FEATURES, default_schedule(), up_state)
            down, _, _ = score_course(course, slot, PET, FEATURES, default_schedule(), down_state)
            assert up > base, (course.name, count)
            assert down < base, (course.name, count)


def test_unrated_course_is_not_penalized_just_because_the_pet_has_feedback():
    rated = make_course(1)
    unrelated = make_course(2, has_park=False, scenery_tags=(), shade_level=0.5)
    # 긍정과 부정 피드백을 섞어 특성 가중치가 거의 중립이 되게 한다.
    state = apply_feedback(EMPTY_STATE, rated, FeedbackInput(5, 5, "just_right", 5, True), 16)
    state = apply_feedback(state, rated, FeedbackInput(1, 1, "hard", 5, False), 16)
    state = PreferenceState(courses=state.courses, feedback_total=state.feedback_total)
    base, _, _ = score_course(unrelated, slot_at(), PET, FEATURES, default_schedule(), EMPTY_STATE)
    after, _, _ = score_course(unrelated, slot_at(), PET, FEATURES, default_schedule(), state)
    assert after == base


def test_feedback_moves_the_total_score():
    course = make_course()
    good = apply_feedback(EMPTY_STATE, course, FeedbackInput(5, 5, "just_right", 5, True), 16)
    bad = apply_feedback(EMPTY_STATE, course, FeedbackInput(1, 1, "hard", 5, False), 16)
    base, _, _ = score_course(course, slot_at(), PET, FEATURES, default_schedule(), EMPTY_STATE)
    up, _, _ = score_course(course, slot_at(), PET, FEATURES, default_schedule(), good)
    down, _, _ = score_course(course, slot_at(), PET, FEATURES, default_schedule(), bad)
    assert up > base > down
