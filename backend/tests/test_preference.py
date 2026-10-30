import pytest

from app.recommender.features import build_features
from app.recommender.preference import (
    NEUTRAL,
    apply_feedback,
    bucket_for_hour,
    feedback_signal,
    predict_from_attributes,
    preference_score,
    record_visit,
    time_bucket_score,
)
from app.recommender.types import FeedbackInput
from tests.conftest import EMPTY_STATE, make_course, make_pet

GREAT = FeedbackInput(5, 5, "just_right", 5, True)
POOR = FeedbackInput(1, 1, "hard", 5, False)
TIMID = build_features(make_pet())
EXPLORER = build_features(make_pet(path_preference="new", personality="curious", novelty_reaction="calm"))


def test_signal_ignores_weather_satisfaction():
    sunny = FeedbackInput(4, 4, "just_right", 5, True)
    stormy = FeedbackInput(4, 4, "just_right", 1, True)
    assert feedback_signal(sunny) == feedback_signal(stormy)


def test_signal_spans_the_full_range():
    assert feedback_signal(GREAT) == 100
    assert feedback_signal(POOR) == pytest.approx(2)


def test_no_feedback_gives_exactly_the_neutral_score():
    score, evidence = preference_score(make_course(), TIMID, EMPTY_STATE)
    assert score == NEUTRAL
    assert "중립값" in evidence[0]


def test_one_five_star_feedback_raises_affinity_but_not_to_the_maximum():
    state = apply_feedback(EMPTY_STATE, make_course(), GREAT, 16)
    assert 60 < state.courses[1].affinity < 80


def test_repeated_good_feedback_keeps_raising_affinity():
    state = EMPTY_STATE
    scores = []
    for _ in range(4):
        state = apply_feedback(state, make_course(), GREAT, 16)
        scores.append(state.courses[1].affinity)
    assert scores == sorted(scores)
    assert scores[-1] > scores[0]


def test_repeated_low_feedback_lowers_the_score():
    state = EMPTY_STATE
    scores = []
    for _ in range(3):
        state = apply_feedback(state, make_course(), POOR, 16)
        scores.append(preference_score(make_course(), TIMID, state)[0])
    assert scores == sorted(scores, reverse=True)
    assert scores[-1] < 30


def test_recent_feedback_counts_more_than_old_feedback():
    course = make_course()
    good_then_bad = apply_feedback(apply_feedback(EMPTY_STATE, course, GREAT, 16), course, POOR, 16)
    bad_then_good = apply_feedback(apply_feedback(EMPTY_STATE, course, POOR, 16), course, GREAT, 16)
    assert bad_then_good.courses[1].affinity > good_then_bad.courses[1].affinity


def test_bad_weather_walks_count_less_toward_the_course():
    course = make_course()
    fair = FeedbackInput(1, 1, "hard", 5, False)
    stormy = FeedbackInput(1, 1, "hard", 1, False)
    assert apply_feedback(EMPTY_STATE, course, stormy, 16).courses[1].affinity > apply_feedback(EMPTY_STATE, course, fair, 16).courses[1].affinity


def test_feedback_generalizes_to_similar_unvisited_courses():
    liked = make_course(1, has_park=True, crowd_level="low", shade_level=0.8, scenery_tags=("forest", "park"))
    similar = make_course(2, has_park=True, crowd_level="low", shade_level=0.7, scenery_tags=("forest", "park"))
    opposite = make_course(3, has_park=False, crowd_level="high", shade_level=0.1, is_paved=False, scenery_tags=("river",))
    state = apply_feedback(EMPTY_STATE, liked, GREAT, 16)
    assert predict_from_attributes(state.attribute_weights, similar) > 55
    assert predict_from_attributes(state.attribute_weights, opposite) < 50
    assert preference_score(similar, TIMID, state)[0] > NEUTRAL


def test_feedback_for_one_course_does_not_count_as_a_visit_elsewhere():
    state = apply_feedback(EMPTY_STATE, make_course(1), GREAT, 16)
    assert 2 not in state.courses
    assert state.feedback_total == 1


def test_familiar_lover_gets_a_bonus_on_a_course_they_liked():
    course = make_course()
    state = apply_feedback(EMPTY_STATE, course, GREAT, 16)
    without_visit, _ = preference_score(course, TIMID, state)
    with_visit, evidence = preference_score(course, TIMID, record_visit(state, course.id))
    assert with_visit > without_visit
    assert any("익숙한 길" in line for line in evidence)


def test_familiar_bonus_is_not_given_to_a_disliked_course():
    course = make_course()
    state = record_visit(apply_feedback(EMPTY_STATE, course, POOR, 16), course.id)
    _, evidence = preference_score(course, TIMID, state)
    assert not any("익숙한 길" in line for line in evidence)


def test_explorer_loses_points_on_an_overvisited_course():
    course = make_course()
    state = apply_feedback(EMPTY_STATE, course, GREAT, 16)
    once, _ = preference_score(course, EXPLORER, record_visit(state, course.id))
    for _ in range(5):
        state = record_visit(state, course.id)
    many, evidence = preference_score(course, EXPLORER, state)
    assert many < once
    assert any("번 다녀온" in line for line in evidence)


def test_score_stays_in_range_after_many_updates():
    state = EMPTY_STATE
    course = make_course()
    for _ in range(100):
        state = record_visit(apply_feedback(state, course, GREAT, 16), course.id)
    assert 0 <= preference_score(course, TIMID, state)[0] <= 100
    assert 0 <= predict_from_attributes(state.attribute_weights, course) <= 100


def test_state_updates_do_not_mutate_the_previous_state():
    state = apply_feedback(EMPTY_STATE, make_course(), GREAT, 16)
    assert EMPTY_STATE.courses == {}
    assert EMPTY_STATE.feedback_total == 0
    assert state.feedback_total == 1


def test_time_bucket_learns_from_feedback_including_weather():
    assert time_bucket_score(EMPTY_STATE, 16) == NEUTRAL
    good = apply_feedback(EMPTY_STATE, make_course(), GREAT, 16)
    assert time_bucket_score(good, 17) > NEUTRAL
    assert time_bucket_score(good, 8) == NEUTRAL
    stormy = apply_feedback(EMPTY_STATE, make_course(), FeedbackInput(5, 5, "just_right", 1, True), 16)
    assert time_bucket_score(stormy, 16) < time_bucket_score(good, 16)


@pytest.mark.parametrize("hour,bucket", [(6, "morning"), (12, "lunch"), (16, "afternoon"), (19, "evening"), (2, "night")])
def test_every_hour_has_a_bucket(hour, bucket):
    assert bucket_for_hour(hour) == bucket
