"""코스 6개 평가 항목과 가중합.

모든 항목은 0~100점으로 정규화한다. 가중치는 기획서 값을 그대로 쓰고, 피드백이 쌓일수록
과거 선호도가 중립값에서 벗어난 만큼을 더 강하게 반영한다.
"""
import math

from app.recommender.preference import DISLIKED_AFFINITY, NEUTRAL, preference_score
from app.recommender.types import (
    CourseData,
    CoursePreference,
    FactorScore,
    PetFeatures,
    PetProfile,
    PreferenceState,
    Schedule,
    SlotEvaluation,
)

INITIAL_WEIGHTS = {
    "weather": 0.25,
    "personality": 0.25,
    "activity": 0.15,
    "schedule": 0.15,
    "safety": 0.10,
    "preference": 0.10,
}
FACTOR_LABELS = {
    "weather": "날씨 적합도",
    "personality": "반려동물 성향 적합도",
    "activity": "활동량 적합도",
    "schedule": "보호자 일정 적합도",
    "safety": "안전 시설 적합도",
    "preference": "과거 선호도",
}
MAX_PREFERENCE_WEIGHT_GAIN = 0.20
SAFETY_FACILITIES = ("toilets", "police", "surveillance", "veterinary")

LIGHTING_VALUE = {"good": 1.0, "partial": 0.6, "poor": 0.2, "unknown": 0.5}
TRAFFIC_VALUE = {"low": 1.0, "medium": 0.6, "high": 0.2}
CROWD_VALUE = {"low": 0.0, "medium": 0.5, "high": 1.0}
LIGHTING_TEXT = {"good": "조명 양호", "partial": "일부 구간 조명", "poor": "조명 부족", "unknown": "조명 정보 없음"}
CROWD_TEXT = {"low": "한적한 편", "medium": "보통", "high": "붐비는 편"}
FACILITY_LABELS = {
    "toilets": "화장실",
    "drinking_water": "음수대",
    "bench": "벤치",
    "waste_basket": "쓰레기통",
    "police": "경찰시설",
    "surveillance": "CCTV",
    "veterinary": "동물병원",
}


def _clip(value: float) -> float:
    return max(0.0, min(100.0, value))


def adaptive_weights(feedback_total: int) -> dict[str, float]:
    """피드백이 쌓일수록 과거 선호도의 반영 강도를 키운다. 나머지 항목은 초기 가중치 그대로다."""
    preference = INITIAL_WEIGHTS["preference"] + MAX_PREFERENCE_WEIGHT_GAIN * feedback_total / (feedback_total + 2)
    return {**INITIAL_WEIGHTS, "preference": preference}


def _contribution(key: str, score: float, weights: dict[str, float]) -> float:
    if key != "preference":
        return weights[key] * score
    # 중립값에서 벗어난 만큼만 강도를 키운다. 그래서 좋은 피드백은 항상 점수를 올리고,
    # 평가하지 않은 코스는 강도가 커져도 깎이지 않는다.
    return INITIAL_WEIGHTS[key] * NEUTRAL + weights[key] * (score - NEUTRAL)


def is_disliked(preference: CoursePreference) -> bool:
    return preference.feedback_count > 0 and preference.affinity < DISLIKED_AFFINITY


def familiarity(course: CourseData, state: PreferenceState) -> float:
    """0~1. 실제 방문 기록이 쌓일수록 높아지고, 집 근처 일상 코스는 처음부터 어느 정도 익숙하다."""
    current = state.courses.get(course.id, CoursePreference())
    neighborhood = 0.75 if course.is_familiar else 0.0
    # 싫어한 코스는 자주 갔어도 '익숙해서 좋은 길'이 아니다. 방문 수를 빼고 원래 익숙함도 줄인다.
    if is_disliked(current):
        return neighborhood * current.affinity / DISLIKED_AFFINITY
    return max(neighborhood, 1 - 0.5**current.visit_count)


def score_weather(course: CourseData, slot: SlotEvaluation, features: PetFeatures) -> tuple[float, tuple[str, ...]]:
    weather = slot.weather
    score = slot.comfort
    evidence = [f"{slot.start:%H}시 체감 {weather.apparent_temperature:.0f}°C, 강수 확률 {weather.precipitation_probability:.0f}%"]

    if weather.apparent_temperature >= features.comfort_high - 2:
        score += (course.shade_level - 0.5) * 30
        if course.shade_level >= 0.6:
            evidence.append("더운 시간에 그늘이 많은 코스")
        elif course.shade_level <= 0.3:
            evidence.append("더운 시간에 그늘이 적은 코스")
    if weather.is_day and weather.uv_index is not None and weather.uv_index >= 6:
        score += (course.shade_level - 0.5) * 10

    wet = slot.rain_overlap_min > 0 or weather.precipitation_probability >= 50
    if wet and not course.is_paved:
        score -= 15
        evidence.append("비가 오면 미끄러울 수 있는 비포장길")

    if weather.wind_speed >= 6:
        if "river" in course.scenery_tags:
            score -= 10
            evidence.append(f"초속 {weather.wind_speed:.0f}m 바람을 그대로 맞는 강변")
        elif course.shade_level >= 0.6:
            score += 4

    if slot.rain_overlap_min > 0:
        score -= slot.rain_overlap_min / slot.duration_min * 40
        evidence.append(f"산책 중 {slot.rain_overlap_min}분이 비 예보 시간과 겹침")
    elif slot.before_rain:
        evidence.append(f"{slot.rain_onset:%H}시 비 예보 전에 끝나는 코스")

    return _clip(score), tuple(evidence)


def score_personality(
    course: CourseData,
    pet: PetProfile,
    features: PetFeatures,
    state: PreferenceState,
) -> tuple[float, tuple[str, ...]]:
    known = familiarity(course, state)
    novelty = features.novelty_tolerance
    path_score = 100 * (known * (1 - novelty) + (1 - known) * novelty)

    crowd_score = 100 * (1 - CROWD_VALUE[course.crowd_level] * (1 - features.crowd_tolerance))

    tags = set(course.scenery_tags)
    if pet.personality == "active":
        temperament = 50 + 25 * ("river" in tags or "open" in tags) + 25 * (course.distance_km >= features.ideal_distance_km)
    elif pet.personality == "curious":
        temperament = 40 + min(60, 20 * len(tags))
    else:
        temperament = 30 + 40 * (course.traffic_exposure == "low") + 30 * course.has_park

    evidence = []
    if is_disliked(state.courses.get(course.id, CoursePreference())):
        evidence.append("지난 피드백이 낮았던 코스")
    elif novelty < 0.4:
        evidence.append("익숙한 코스" if known >= 0.5 else "아직 낯선 코스")
    elif novelty > 0.6:
        evidence.append("새로운 경험을 주는 코스" if known < 0.5 else "이미 익숙한 코스")
    evidence.append(f"혼잡도: {CROWD_TEXT[course.crowd_level]}")

    return _clip(0.45 * path_score + 0.3 * crowd_score + 0.25 * temperament), tuple(evidence)


def score_activity(course: CourseData, features: PetFeatures, slot: SlotEvaluation) -> tuple[float, tuple[str, ...]]:
    ideal = max(0.3, features.ideal_distance_km * slot.ideal_factor)
    ratio = course.distance_km / ideal
    score = 100 * math.exp(-(math.log(ratio) ** 2) / (2 * 0.45**2))
    if course.difficulty == "moderate":
        score *= 0.8 + 0.2 * features.hill_tolerance
    elif course.difficulty == "hard":
        score *= 0.5 + 0.5 * features.hill_tolerance

    evidence = [f"권장 약 {ideal:.1f}km, 이 코스 {course.distance_km:.1f}km"]
    if course.difficulty != "easy":
        evidence.append("오르막이 있는 코스")
    return _clip(score), tuple(evidence)


def score_schedule(course: CourseData, slot: SlotEvaluation, schedule: Schedule) -> tuple[float, tuple[str, ...]]:
    target = schedule.preferred_duration_min
    duration = course.duration_min
    if duration <= target:
        shortfall = max(0.0, target * 0.5 - duration) / (target * 0.5)
        score = 100 - shortfall * 30
    else:
        score = 100 - (duration - target) / target * 120
    evidence = [f"희망 {target}분, 코스 약 {duration}분"]
    if not slot.fits_window:
        score *= 0.4
        evidence.append(f"가능 시간 {slot.window.end_hour}시를 넘겨요")
    return _clip(score), tuple(evidence)


def score_safety(course: CourseData, slot: SlotEvaluation) -> tuple[float, tuple[str, ...]]:
    lighting = LIGHTING_VALUE[course.lighting]
    traffic = TRAFFIC_VALUE[course.traffic_exposure]
    facility_count = sum(course.facility_counts.get(kind, 0) for kind in SAFETY_FACILITIES)
    facilities = min(1.0, facility_count / 3)

    if slot.is_dark:
        score = 0.5 * lighting + 0.2 * traffic + 0.1 * course.has_park + 0.1 * course.is_paved + 0.1 * facilities
    else:
        score = 0.15 * lighting + 0.35 * traffic + 0.2 * course.has_park + 0.15 * course.is_paved + 0.15 * facilities

    evidence = []
    if slot.is_dark:
        evidence.append(f"해가 진 뒤 산책, {LIGHTING_TEXT[course.lighting]}(팀 조사 추정값)")
    if course.has_park:
        evidence.append("공원 포함")
    if course.traffic_exposure == "low":
        evidence.append("차량 노출이 적은 길")
    elif course.traffic_exposure == "high":
        evidence.append("차량 노출이 많은 길")
    return _clip(100 * score), tuple(evidence) or ("특이사항 없음",)


def score_course(
    course: CourseData,
    slot: SlotEvaluation,
    pet: PetProfile,
    features: PetFeatures,
    schedule: Schedule,
    state: PreferenceState,
) -> tuple[float, tuple[FactorScore, ...], float]:
    """코스를 출발 시각 하나에 대해 평가한다. (총점, 항목별 점수, 과거 선호도 점수)를 돌려준다."""
    weights = adaptive_weights(state.feedback_total)
    preference, preference_evidence = preference_score(course, features, state)
    raw = {
        "weather": score_weather(course, slot, features),
        "personality": score_personality(course, pet, features, state),
        "activity": score_activity(course, features, slot),
        "schedule": score_schedule(course, slot, schedule),
        "safety": score_safety(course, slot),
        "preference": (preference, preference_evidence),
    }
    contributions = {key: _contribution(key, score, weights) for key, (score, _) in raw.items()}
    factors = tuple(
        FactorScore(
            key=key,
            label=FACTOR_LABELS[key],
            score=round(score, 1),
            weight=round(weights[key], 4),
            contribution=round(contributions[key], 2),
            evidence=evidence,
        )
        for key, (score, evidence) in raw.items()
    )
    return round(_clip(sum(contributions.values())), 2), factors, preference
