from app.recommender.course_scoring import score_course
from app.recommender.explain import DISCLAIMER, build_explanation, has_final_consonant, hour_label, object_particle
from app.recommender.features import build_features
from app.recommender.preference import apply_feedback, record_visit
from app.recommender.timeslots import evaluate_slot
from app.recommender.types import FeedbackInput, TimeWindow
from tests.conftest import EMPTY_STATE, NOW, default_schedule, make_course, make_forecast, make_pet

RAIN_AFTER_17 = lambda t: {"precipitation_probability": 85, "precipitation_mm": 1.5} if t.hour >= 17 else {}


def explain(pet=None, course=None, hour=16, rule=None, state=EMPTY_STATE):
    pet = pet or make_pet()
    course = course or make_course()
    features = build_features(pet)
    rows = {row.time: row for row in make_forecast(rule=rule)}
    slot = evaluate_slot(NOW.replace(hour=hour), course.duration_min, TimeWindow(16, 20), rows, features, state, NOW)
    _, factors, _ = score_course(course, slot, pet, features, default_schedule(), state)
    return build_explanation(pet, features, course, slot, factors, state)


def test_produces_the_exact_sentence_from_the_specification():
    result = explain(rule=RAIN_AFTER_17)
    assert result.summary == "낯선 길을 싫어하는 두부를 위해 익숙한 공원 코스를 골랐어요. 비가 오기 전 짧게 다녀올 수 있어요."


def test_particle_follows_the_final_consonant():
    assert has_final_consonant("콩") is True
    assert has_final_consonant("두부") is False
    assert has_final_consonant("Coco") is False
    assert object_particle("콩") == "을"
    assert object_particle("두부") == "를"
    assert "콩을 위해" in explain(pet=make_pet(name="콩")).summary


def test_park_is_not_mentioned_for_a_course_without_a_park():
    result = explain(course=make_course(has_park=False, scenery_tags=("residential",)))
    assert "공원" not in result.summary
    assert "동네 코스" in result.summary


def test_unknown_lighting_is_never_called_lit():
    result = explain(course=make_course(lighting="unknown"), hour=19)
    assert "조명이 있는" not in result.summary
    assert any("어두울" in caution for caution in result.cautions)


def test_good_lighting_is_mentioned_only_after_dark():
    assert "조명" in explain(course=make_course(lighting="good"), hour=19).summary
    assert "조명" not in explain(course=make_course(lighting="good"), hour=16).summary


def test_rain_sentence_only_appears_when_rain_is_actually_coming():
    assert "비가 오기 전" not in explain().summary
    assert "비가 오기 전" in explain(rule=RAIN_AFTER_17).summary


def test_long_course_is_not_called_short():
    result = explain(course=make_course(duration_min=45, distance_km=2.7), rule=lambda t: {"precipitation_probability": 85, "precipitation_mm": 1.5} if t.hour >= 18 else {})
    assert "비가 오기 전에 다녀올 수 있어요." in result.summary
    assert "짧게" not in result.summary


def test_new_path_lover_gets_a_different_reason():
    pet = make_pet(name="초코", path_preference="new", personality="curious", novelty_reaction="calm")
    result = explain(pet=pet, course=make_course(is_familiar=False))
    assert "새로운 길을 좋아하는 초코를 위해" in result.summary


def test_liked_course_mentions_past_satisfaction():
    course = make_course()
    state = record_visit(apply_feedback(EMPTY_STATE, course, FeedbackInput(5, 5, "just_right", 5, True), 16), course.id)
    assert "지난번 만족도가 높았던" in explain(course=course, state=state).summary


def test_disliked_course_is_not_called_familiar_or_new():
    course = make_course()
    state = EMPTY_STATE
    for _ in range(3):
        state = apply_feedback(record_visit(state, course.id), course, FeedbackInput(1, 1, "hard", 5, False), 16)
    summary = explain(course=course, state=state).summary
    assert "지난 만족도는 낮았지만" in summary
    assert "익숙한" not in summary
    assert "처음" not in summary


def test_unfamiliar_course_is_not_called_familiar():
    result = explain(course=make_course(is_familiar=False, crowd_level="medium"))
    assert "익숙한" not in result.summary
    assert "낯선" in result.summary


def test_unvisited_seed_familiar_course_never_claims_past_satisfaction():
    assert "지난번" not in explain().summary


def test_disclaimer_is_always_present():
    assert DISCLAIMER in explain().cautions


def test_cautions_follow_conditions():
    rainy = explain(course=make_course(is_paved=False), rule=lambda t: {"precipitation_probability": 85, "precipitation_mm": 1.5})
    assert any("미끄러울" in caution for caution in rainy.cautions)
    hot = explain(rule=lambda t: {"apparent_temperature": 28.0})
    assert any("노면" in caution for caution in hot.cautions)
    cold = explain(rule=lambda t: {"apparent_temperature": 2.0})
    assert any("추워요" in caution for caution in cold.cautions)
    crowded = explain(course=make_course(crowd_level="high"))
    assert any("두부는 긴장" in caution for caution in crowded.cautions)
    calm = explain()
    assert calm.cautions == (DISCLAIMER,)


def test_details_are_sorted_by_contribution_and_cover_all_factors():
    result = explain()
    assert len(result.details) == 6
    assert all("점:" in line for line in result.details)


def test_hour_label():
    assert hour_label(16) == "오후 4시"
    assert hour_label(9) == "오전 9시"
    assert hour_label(12) == "낮 12시"
    assert hour_label(0) == "자정"
