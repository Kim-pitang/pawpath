from app.recommender.features import build_features, life_stage
from tests.conftest import make_pet


def test_dubu_features_reflect_a_timid_small_dog():
    features = build_features(make_pet())
    assert features.life_stage == "adult"
    assert features.ideal_walk_min == 30
    assert features.ideal_distance_km == 1.5
    assert features.novelty_tolerance < 0.2
    assert features.crowd_tolerance < 0.2


def test_senior_threshold_depends_on_size():
    assert life_stage(8, "large") == "senior"
    assert life_stage(8, "small") == "adult"
    assert life_stage(0.5, "small") == "puppy"


def test_senior_needs_a_shorter_walk_and_narrower_comfort_band():
    adult = build_features(make_pet(size="large", weight_kg=30, age_years=4))
    senior = build_features(make_pet(size="large", weight_kg=30, age_years=9))
    assert senior.ideal_walk_min < adult.ideal_walk_min
    assert senior.comfort_high < adult.comfort_high
    assert senior.comfort_low > adult.comfort_low


def test_high_activity_needs_a_longer_walk():
    low = build_features(make_pet(activity_level="low"))
    high = build_features(make_pet(activity_level="high"))
    assert high.ideal_walk_min > low.ideal_walk_min
    assert high.ideal_distance_km > low.ideal_distance_km


def test_heat_sensitive_pet_reaches_unsafe_heat_earlier():
    tolerant = build_features(make_pet(heat_sensitivity="low"))
    sensitive = build_features(make_pet(heat_sensitivity="high"))
    assert sensitive.unsafe_heat < tolerant.unsafe_heat


def test_new_path_lover_tolerates_novelty():
    features = build_features(make_pet(path_preference="new", personality="curious", novelty_reaction="calm"))
    assert features.novelty_tolerance > 0.6
