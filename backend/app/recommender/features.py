"""반려동물 프로필을 추천 특성값으로 변환한다.

수치는 일반적인 산책 지침을 참고해 정한 서비스 휴리스틱이며 수의학적 기준이 아니다.
"""
from app.recommender.types import PetFeatures, PetProfile

SENIOR_AGE = {"small": 10, "medium": 8, "large": 7}
BASE_WALK_MIN = {"small": 30, "medium": 45, "large": 60}
PACE_KMH = {"small": 3.0, "medium": 3.6, "large": 4.2}
ACTIVITY_MULTIPLIER = {"low": 0.75, "medium": 1.0, "high": 1.3}
LIFE_STAGE_MULTIPLIER = {"puppy": 0.6, "adult": 1.0, "senior": 0.7}

NOVELTY_BY_PATH = {"familiar": 0.2, "new": 0.8}
NOVELTY_BY_REACTION = {"calm": 0.1, "cautious": 0.0, "anxious": -0.15}
NOVELTY_BY_PERSONALITY = {"active": 0.05, "timid": -0.05, "curious": 0.1}
CROWD_BY_PERSONALITY = {"active": 0.8, "curious": 0.6, "timid": 0.2}
CROWD_BY_REACTION = {"calm": 0.1, "cautious": 0.0, "anxious": -0.15}
HILL_BY_ACTIVITY = {"low": 0.3, "medium": 0.6, "high": 0.9}


def life_stage(age_years: float, size: str) -> str:
    if age_years < 1:
        return "puppy"
    if age_years >= SENIOR_AGE[size]:
        return "senior"
    return "adult"


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def build_features(pet: PetProfile) -> PetFeatures:
    stage = life_stage(pet.age_years, pet.size)

    ideal_min = round(BASE_WALK_MIN[pet.size] * ACTIVITY_MULTIPLIER[pet.activity_level] * LIFE_STAGE_MULTIPLIER[stage])
    ideal_km = round(ideal_min / 60 * PACE_KMH[pet.size], 2)

    novelty = _clip01(
        NOVELTY_BY_PATH[pet.path_preference]
        + NOVELTY_BY_REACTION[pet.novelty_reaction]
        + NOVELTY_BY_PERSONALITY[pet.personality]
    )
    crowd = _clip01(CROWD_BY_PERSONALITY[pet.personality] + CROWD_BY_REACTION[pet.novelty_reaction])

    hill = HILL_BY_ACTIVITY[pet.activity_level]
    if stage != "adult":
        hill -= 0.3

    comfort_low, comfort_high = 5.0, 22.0
    if pet.size == "small":
        comfort_low += 1
    elif pet.size == "large":
        comfort_low -= 3
    comfort_high += {"low": 3, "medium": 0, "high": -3}[pet.heat_sensitivity]
    if pet.weight_kg >= 25:
        comfort_high -= 1
    if pet.weight_kg < 5:
        comfort_low += 1
    if stage != "adult":
        comfort_low += 2
        comfort_high -= 2

    return PetFeatures(
        life_stage=stage,
        ideal_walk_min=ideal_min,
        ideal_distance_km=ideal_km,
        novelty_tolerance=round(novelty, 3),
        crowd_tolerance=round(crowd, 3),
        hill_tolerance=round(_clip01(hill), 3),
        comfort_low=comfort_low,
        comfort_high=comfort_high,
        unsafe_cold=comfort_low - 15,
        unsafe_heat=comfort_high + 11,
    )
