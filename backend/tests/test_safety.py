from datetime import datetime

import pytest

from app.recommender.features import build_features
from app.recommender.safety import (
    UNKNOWN_SCORE,
    assess_conditions,
    assess_course,
    assessment_payload,
)
from app.recommender.timeslots import evaluate_slot
from app.recommender.types import TimeWindow
from tests.conftest import EMPTY_STATE, NOW, make_course, make_forecast, make_hour, make_pet, seed_course_data

FEATURES = build_features(make_pet())
WINDOW = TimeWindow(0, 24)


def slot_at(hour=16, duration=25, rule=None, features=FEATURES):
    rows = {row.time: row for row in make_forecast(rule=rule)}
    return evaluate_slot(NOW.replace(hour=hour), duration, WINDOW, rows, features, EMPTY_STATE, NOW)


def item(assessment, key):
    return next(entry for entry in assessment.items if entry.key == key)


def test_every_item_says_where_its_value_came_from():
    assessment = assess_course(make_course(), slot_at(), FEATURES)
    assert {entry.key for entry in assessment.items} >= {"temperature", "rain", "wind", "uv", "time", "lighting", "shade", "traffic", "surface", "facilities", "park"}
    assert all(entry.source in ("forecast", "demo", "observed", "estimated", "unknown") for entry in assessment.items)
    assert all(entry.source_label for entry in assessment.items)


def test_weather_values_are_labeled_as_forecast_not_observed():
    assessment = assess_course(make_course(), slot_at(), FEATURES)
    assert item(assessment, "temperature").source == "forecast"
    demo = assess_course(make_course(), slot_at(), FEATURES, weather_source="demo")
    assert item(demo, "temperature").source == "demo"


def test_missing_lighting_data_is_unverified_and_never_counted_as_safe():
    course = make_course(lighting="unknown")
    lit = item(assess_course(course, slot_at(), FEATURES), "lighting")
    assert lit.status == "unverified"
    assert "확인 불가" in lit.value
    assert lit.score == UNKNOWN_SCORE
    assert lit.source == "unknown"


def test_team_estimate_is_labeled_and_scored_below_a_real_record():
    estimated = item(assess_course(make_course(lighting="good"), slot_at(hour=19), FEATURES), "lighting")
    assert estimated.source == "estimated"
    assert "확인 불가" in estimated.value and "추정" in estimated.value
    recorded_course = make_course(lighting="good", environment={"lit": {"yes": 0.9, "no": 0.0, "unknown": 0.1}})
    recorded = item(assess_course(recorded_course, slot_at(hour=19), FEATURES), "lighting")
    assert recorded.source == "observed"
    assert recorded.status == "ok"
    assert recorded.score > estimated.score


def test_sparse_lighting_records_do_not_count_as_observed():
    course = make_course(lighting="partial", environment={"lit": {"yes": 0.2, "no": 0.0, "unknown": 0.8}})
    assert item(assess_course(course, slot_at(), FEATURES), "lighting").source == "estimated"


def test_no_tree_record_does_not_mean_no_shade():
    course = make_course(shade_level=0.5, environment={"trees": 0.0})
    shade = item(assess_course(course, slot_at(), FEATURES), "shade")
    assert shade.status == "unverified"
    assert shade.source == "estimated"


def test_tree_records_count_as_observed():
    course = make_course(environment={"trees": 0.6})
    shade = item(assess_course(course, slot_at(), FEATURES), "shade")
    assert shade.source == "observed"
    assert shade.status == "ok"


def test_mild_temperature_is_not_called_hot():
    # 쾌적 범위 안(체감 21°C, 상한 22°C)에서는 그늘이 적어도 더위 경고를 하지 않는다.
    rule = lambda t: {"apparent_temperature": 21.0}
    assessment = assess_course(make_course(shade_level=0.2), slot_at(rule=rule), FEATURES)
    assert not any("더운" in risk for risk in assessment.risks)
    hot = assess_course(make_course(shade_level=0.2), slot_at(rule=lambda t: {"apparent_temperature": 24.0}), FEATURES)
    assert any("더운 시간" in risk for risk in hot.risks)


def test_no_facility_record_is_not_reported_as_no_facility():
    entry = item(assess_course(make_course(), slot_at(), FEATURES), "facilities")
    assert entry.status == "unverified"
    assert "실제로 없다는 뜻은 아니에요" in entry.detail


def test_osm_road_data_replaces_the_estimate():
    busy = make_course(environment={"road": {"pedestrian": 0.1, "local": 0.2, "major": 0.7, "unknown": 0.0}})
    quiet = make_course(environment={"road": {"pedestrian": 0.9, "local": 0.1, "major": 0.0, "unknown": 0.0}})
    busy_item = item(assess_course(busy, slot_at(), FEATURES), "traffic")
    quiet_item = item(assess_course(quiet, slot_at(), FEATURES), "traffic")
    assert busy_item.source == quiet_item.source == "observed"
    assert busy_item.status == "caution"
    assert quiet_item.status == "ok"
    assert quiet_item.score > busy_item.score


def test_major_road_after_dark_is_danger():
    course = make_course(environment={"road": {"pedestrian": 0.1, "local": 0.2, "major": 0.7, "unknown": 0.0}})
    assert item(assess_course(course, slot_at(hour=19), FEATURES), "traffic").status == "danger"


def test_missing_uv_is_unverified():
    entry = item(assess_course(make_course(), slot_at(rule=lambda t: {"uv_index": None}), FEATURES), "uv")
    assert entry.status == "unverified"
    assert entry.score is None


@pytest.mark.parametrize(
    "rule,key,status",
    [
        (lambda t: {"apparent_temperature": 24.0}, "temperature", "caution"),
        (lambda t: {"apparent_temperature": 29.0}, "temperature", "danger"),
        (lambda t: {"apparent_temperature": 3.0}, "temperature", "caution"),
        (lambda t: {"apparent_temperature": -3.0}, "temperature", "danger"),
        (lambda t: {"wind_speed": 7.0}, "wind", "caution"),
        (lambda t: {"wind_speed": 11.0}, "wind", "danger"),
        (lambda t: {"uv_index": 7.0}, "uv", "caution"),
        (lambda t: {"uv_index": 10.0}, "uv", "danger"),
        (lambda t: {"precipitation_probability": 55.0}, "rain", "caution"),
    ],
)
def test_risk_levels_follow_conditions(rule, key, status):
    assert item(assess_course(make_course(), slot_at(rule=rule), FEATURES), key).status == status


def test_good_conditions_have_no_risks_and_no_penalty():
    assessment = assess_course(make_course(), slot_at(), FEATURES)
    assert assessment.risks == ()
    assert assessment.penalty == 0
    assert assessment.blocked_reasons == ()


def test_risks_explain_each_factor():
    assessment = assess_course(make_course(), slot_at(rule=lambda t: {"apparent_temperature": 29.0, "wind_speed": 7.0}), FEATURES)
    assert any("더위" in risk for risk in assessment.risks)
    assert any("바람" in risk for risk in assessment.risks)
    assert assessment.level == "danger"
    assert assessment.penalty == pytest.approx(6.5)


def test_penalty_is_capped():
    rule = lambda t: {"apparent_temperature": 29.0, "wind_speed": 12.0, "uv_index": 11.0, "precipitation_mm": 5.0}
    assert assess_course(make_course(), slot_at(rule=rule), FEATURES).penalty <= 15


def test_unpaved_course_is_blocked_while_it_rains():
    rule = lambda t: {"precipitation_probability": 85.0, "precipitation_mm": 1.5}
    assessment = assess_course(make_course(is_paved=False), slot_at(rule=rule), FEATURES)
    assert assessment.level == "blocked"
    assert any("미끄러" in reason for reason in assessment.blocked_reasons)
    assert assess_course(make_course(is_paved=True), slot_at(rule=rule), FEATURES).level != "blocked"


def test_long_walk_in_extreme_heat_without_confirmed_shade_is_blocked():
    rule = lambda t: {"apparent_temperature": 30.0}
    exposed = make_course(shade_level=0.2)
    assert assess_course(exposed, slot_at(duration=50, rule=rule), FEATURES).level == "blocked"
    # 짧은 산책이나 그늘이 확인된 코스는 제외하지 않는다.
    assert assess_course(exposed, slot_at(duration=20, rule=rule), FEATURES).level != "blocked"
    shaded = make_course(shade_level=0.2, environment={"trees": 0.7})
    assert assess_course(shaded, slot_at(duration=50, rule=rule), FEATURES).level != "blocked"


def test_dark_poorly_lit_course_is_blocked_only_for_sensitive_pets():
    dim = make_course(lighting="poor")
    assert assess_course(dim, slot_at(hour=19), FEATURES).level == "blocked"
    bold = build_features(make_pet(personality="active", novelty_reaction="calm"))
    slot = slot_at(hour=19, features=bold)
    assessment = assess_course(dim, slot, bold)
    assert assessment.level == "danger"
    assert assessment.blocked_reasons == ()


def test_strong_wind_blocks_riverside_course_only():
    rule = lambda t: {"wind_speed": 11.0}
    river = make_course(scenery_tags=("river",))
    assert assess_course(river, slot_at(rule=rule), FEATURES).level == "blocked"
    assert assess_course(make_course(), slot_at(rule=rule), FEATURES).level == "danger"


def test_all_seed_courses_produce_a_valid_assessment_day_and_night():
    for course in seed_course_data():
        for hour in (10, 16, 19):
            assessment = assess_course(course, slot_at(hour=hour, duration=course.duration_min), FEATURES)
            assert 0 <= assessment.score <= 100
            assert assessment.level in ("good", "caution", "danger", "blocked")
            assert "보장하지 않아요" in assessment.disclaimer


def test_conditions_only_assessment_for_the_safety_endpoint():
    now = datetime(2026, 10, 30, 12, 0)
    mild = assess_conditions(make_hour(now), FEATURES)
    assert mild.level == "good"
    storm = assess_conditions(make_hour(now, precipitation_probability=95, precipitation_mm=6), FEATURES)
    assert storm.level == "danger"
    assert storm.score < mild.score


def test_payload_is_json_ready():
    payload = assessment_payload(assess_course(make_course(), slot_at(), FEATURES))
    assert payload["level"] == "caution" or payload["level"] == "good"
    assert isinstance(payload["items"][0], dict)
    assert payload["items"][0]["source_label"]
