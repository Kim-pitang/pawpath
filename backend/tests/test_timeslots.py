from datetime import datetime, timedelta

from app.recommender.features import build_features
from app.recommender.preference import apply_feedback
from app.recommender.timeslots import (
    candidate_starts,
    evaluate_slot,
    hour_comfort,
    recommend_times,
    unsafe_reason,
)
from app.recommender.types import FeedbackInput, TimeWindow
from tests.conftest import EMPTY_STATE, NOW, default_schedule, make_course, make_forecast, make_hour, make_pet

FEATURES = build_features(make_pet())


def forecast_map(rows):
    return {row.time: row for row in rows}


def test_candidates_stay_inside_the_guardian_window():
    starts = candidate_starts(NOW, (TimeWindow(16, 20),))
    assert [start.hour for start, _ in starts] == [16, 17, 18, 19]
    assert all(start.date() == NOW.date() for start, _ in starts)


def test_candidates_roll_to_tomorrow_after_the_window_passes():
    now = datetime(2026, 10, 30, 22, 30)
    starts = candidate_starts(now, (TimeWindow(16, 20),))
    assert [start.hour for start, _ in starts] == [16, 17, 18, 19]
    assert all(start.date() == now.date() + timedelta(days=1) for start, _ in starts)


def test_comfort_drops_with_rain_heat_and_cold():
    mild = hour_comfort(make_hour(NOW), FEATURES)
    assert mild > 90
    assert hour_comfort(make_hour(NOW, precipitation_probability=90, precipitation_mm=2), FEATURES) < 40
    assert hour_comfort(make_hour(NOW, apparent_temperature=30, temperature=30), FEATURES) < mild
    assert hour_comfort(make_hour(NOW, apparent_temperature=-2, temperature=-2), FEATURES) < mild


def test_comfort_stays_in_range_for_extreme_weather():
    extreme = make_hour(NOW, apparent_temperature=45, precipitation_probability=100, precipitation_mm=30, wind_speed=30, uv_index=14)
    assert 0 <= hour_comfort(extreme, FEATURES) <= 100


def test_unsafe_conditions_are_flagged():
    assert "비" in unsafe_reason(make_hour(NOW, precipitation_mm=5), FEATURES)
    assert "더위" in unsafe_reason(make_hour(NOW, apparent_temperature=35), FEATURES)
    assert "추위" in unsafe_reason(make_hour(NOW, apparent_temperature=-10), FEATURES)
    assert "강풍" in unsafe_reason(make_hour(NOW, wind_speed=15), FEATURES)
    assert unsafe_reason(make_hour(NOW), FEATURES) is None


def test_recommends_the_dry_slot_before_rain():
    rows = make_forecast(rule=lambda t: {"precipitation_probability": 90, "precipitation_mm": 2} if t.hour >= 17 else {})
    result = recommend_times(NOW, forecast_map(rows), FEATURES, default_schedule(), EMPTY_STATE)
    assert result.best_slots[0].start.hour == 16
    assert result.best_slots[0].before_rain is True


def test_walk_is_shortened_to_fit_before_rain():
    now = datetime(2026, 10, 30, 15, 0)
    rows = make_forecast(now, rule=lambda t: {"precipitation_probability": 90, "precipitation_mm": 2} if t.hour >= 17 else {})
    schedule = default_schedule(windows=(TimeWindow(16, 20),), preferred_duration_min=120)
    pet = make_pet(size="large", weight_kg=30, activity_level="high")
    result = recommend_times(now, forecast_map(rows), build_features(pet), schedule, EMPTY_STATE)
    assert result.best_slots[0].duration_min <= 60
    assert result.best_slots[0].rain_overlap_min == 0


def test_avoids_the_hot_hour_when_a_cooler_one_exists():
    rows = make_forecast(rule=lambda t: {"apparent_temperature": 33 - (t.hour - 16) * 3} if 16 <= t.hour < 20 else {})
    result = recommend_times(NOW, forecast_map(rows), FEATURES, default_schedule(), EMPTY_STATE)
    assert result.best_slots[0].start.hour >= 18
    excluded = next(slot for slot in result.all_slots if slot.start.hour == 16)
    assert excluded.unsafe_reason is not None


def test_cold_weather_shortens_the_recommended_walk():
    mild = recommend_times(NOW, forecast_map(make_forecast()), FEATURES, default_schedule(), EMPTY_STATE)
    cold_rows = make_forecast(rule=lambda t: {"apparent_temperature": 0.0, "temperature": 0.0})
    cold = recommend_times(NOW, forecast_map(cold_rows), FEATURES, default_schedule(), EMPTY_STATE)
    assert cold.recommended_duration_min < mild.recommended_duration_min


def test_all_heavy_rain_leaves_no_best_slot():
    rows = make_forecast(rule=lambda t: {"precipitation_probability": 95, "precipitation_mm": 6})
    result = recommend_times(NOW, forecast_map(rows), FEATURES, default_schedule(), EMPTY_STATE)
    assert result.best_slots == ()
    assert all(slot.unsafe_reason for slot in result.all_slots)


def test_two_walks_per_day_are_spaced_apart():
    schedule = default_schedule(windows=(TimeWindow(7, 10), TimeWindow(16, 20)), walks_per_day=2)
    now = datetime(2026, 10, 30, 6, 0)
    result = recommend_times(now, forecast_map(make_forecast(now)), FEATURES, schedule, EMPTY_STATE)
    assert len(result.best_slots) == 2
    assert abs(result.best_slots[1].start - result.best_slots[0].start) >= timedelta(hours=3)


def test_walk_overrunning_the_window_scores_lower():
    start = NOW.replace(hour=19)
    rows = forecast_map(make_forecast())
    fits = evaluate_slot(start, 30, TimeWindow(16, 20), rows, FEATURES, EMPTY_STATE, NOW)
    overruns = evaluate_slot(start, 120, TimeWindow(16, 20), rows, FEATURES, EMPTY_STATE, NOW)
    assert fits.fits_window is True
    assert overruns.fits_window is False
    assert overruns.components["fit"] < fits.components["fit"]


def test_timid_pet_prefers_daylight():
    rows = forecast_map(make_forecast())
    light = evaluate_slot(NOW.replace(hour=16), 30, TimeWindow(16, 20), rows, FEATURES, EMPTY_STATE, NOW)
    dark = evaluate_slot(NOW.replace(hour=19), 30, TimeWindow(16, 20), rows, FEATURES, EMPTY_STATE, NOW)
    assert dark.is_dark is True
    assert light.components["daylight"] > dark.components["daylight"]


def test_learned_time_preference_changes_the_recommended_slot():
    rows = forecast_map(make_forecast())
    schedule = default_schedule(windows=(TimeWindow(11, 13), TimeWindow(16, 18)))
    now = datetime(2026, 10, 30, 10, 30)
    before = recommend_times(now, rows, FEATURES, schedule, EMPTY_STATE)
    assert before.best_slots[0].start.hour == 11

    state = EMPTY_STATE
    great = FeedbackInput(5, 5, "just_right", 5, True)
    for _ in range(8):
        state = apply_feedback(state, make_course(), great, walk_hour=16)
    after = recommend_times(now, rows, FEATURES, schedule, state)
    assert after.best_slots[0].start.hour == 16
