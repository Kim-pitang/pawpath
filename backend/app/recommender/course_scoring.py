"""코스 6개 평가 항목과 가중합.

모든 항목은 0~100점으로 정규화한다. 가중치는 기획서 값을 그대로 쓰고, 피드백이 쌓일수록
과거 선호도가 중립값에서 벗어난 만큼을 더 강하게 반영한다.
"""
import math
from collections.abc import Mapping

from app.recommender.config import BASE_WEIGHTS, DEFAULT_CONFIG, FEEDBACK_RAMP, ScoringConfig
from app.recommender.preference import (
    BUCKET_LABELS,
    DISLIKED_AFFINITY,
    GENERALIZATION_DISCOUNT,
    NEUTRAL,
    PRIOR_STRENGTH,
    predict_from_attributes,
    preference_score,
    preferred_time_match,
    user_preference_score,
)
from dataclasses import replace

from app.recommender.profile import LearnedProfile, adjusted_ideal_km
from app.recommender.safety import assess_course
from app.recommender.types import (
    CourseData,
    CoursePreference,
    FactorScore,
    GroupScore,
    PetFeatures,
    PetProfile,
    PreferenceState,
    Schedule,
    SlotEvaluation,
)

INITIAL_WEIGHTS = BASE_WEIGHTS
FACTOR_LABELS = {
    "weather": "날씨 적합도",
    "personality": "반려동물 성향 적합도",
    "activity": "활동량 적합도",
    "schedule": "보호자 일정 적합도",
    "safety": "안전 시설 적합도",
    "preference": "과거 선호도",
    "user_preference": "사용자 선호도",
}
# 응답에서 보여 주는 6개 평가 묶음. 세부 항목(factors)은 호환을 위해 그대로 둔다.
SCORE_GROUPS = (
    ("pet_fit", "반려동물 적합도", ("personality", "activity")),
    ("user_preference", "사용자 선호도", ("user_preference",)),
    ("weather", "날씨 적합도", ("weather",)),
    ("safety", "산책 안전성", ("safety",)),
    ("time", "시간 적합도", ("schedule",)),
    ("past_satisfaction", "과거 만족도", ("preference",)),
)

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


def adaptive_weights(feedback_total: int, config: ScoringConfig = DEFAULT_CONFIG) -> dict[str, float]:
    """피드백이 쌓일수록 과거 선호도의 반영 강도를 키운다. 나머지 항목은 설정된 가중치 그대로다."""
    gain = config.max_preference_gain * feedback_total / (feedback_total + 2)
    return {**config.weights, "preference": config.weights["preference"] + gain, "user_preference": config.user_preference_weight}


def _contribution(key: str, score: float, weights: dict[str, float], config: ScoringConfig) -> float:
    # 중립값에서 벗어난 만큼만 강도를 키운다. 그래서 좋은 피드백은 항상 점수를 올리고,
    # 평가하지 않은 코스는 강도가 커져도 깎이지 않는다.
    if key == "preference":
        return config.weights[key] * NEUTRAL + weights[key] * (score - NEUTRAL)
    if key == "user_preference":
        return weights[key] * (score - NEUTRAL)
    return weights[key] * score


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
            evidence.append("더운 시간에 그늘이 많을 것으로 추정되는 코스")
        elif course.shade_level <= 0.3:
            evidence.append("더운 시간에 그늘이 적을 것으로 추정되는 코스")
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
    evidence.append("혼잡도: 확인 불가" if "crowd_level" in course.unknown else f"혼잡도: {CROWD_TEXT[course.crowd_level]}")

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


def score_safety(course: CourseData, slot: SlotEvaluation, features: PetFeatures) -> tuple[float, tuple[str, ...]]:
    assessment = assess_course(course, slot, features)
    evidence = [risk.rstrip(".") for risk in assessment.risks]
    if assessment.unverified:
        evidence.append(f"확인 불가: {', '.join(assessment.unverified)}")
    return assessment.score, tuple(evidence) or ("특이사항 없음",)


def score_breakdown(factors: tuple[FactorScore, ...]) -> list[dict]:
    """세부 항목을 6개 평가 묶음으로 합친다."""
    by_key = {factor.key: factor for factor in factors}
    groups = []
    for key, label, members in SCORE_GROUPS:
        parts = [by_key[member] for member in members if member in by_key]
        weight = sum(part.weight for part in parts)
        score = sum(part.score * part.weight for part in parts) / weight if weight else 0.0
        groups.append(
            {
                "key": key,
                "label": label,
                "score": round(score, 1),
                "weight": round(weight, 4),
                "contribution": round(sum(part.contribution for part in parts), 2),
                "evidence": [line for part in parts for line in part.evidence],
            }
        )
    return groups


def score_course(
    course: CourseData,
    slot: SlotEvaluation,
    pet: PetProfile,
    features: PetFeatures,
    schedule: Schedule,
    state: PreferenceState,
    config: ScoringConfig = DEFAULT_CONFIG,
) -> tuple[float, tuple[FactorScore, ...], float]:
    """코스를 출발 시각 하나에 대해 평가한다. (총점, 항목별 점수, 과거 선호도 점수)를 돌려준다."""
    weights = adaptive_weights(state.feedback_total, config)
    preference, preference_evidence = preference_score(course, features, state)
    raw = {
        "weather": score_weather(course, slot, features),
        "personality": score_personality(course, pet, features, state),
        "activity": score_activity(course, features, slot),
        "schedule": score_schedule(course, slot, schedule),
        "safety": score_safety(course, slot, features),
        "preference": (preference, preference_evidence),
        "user_preference": user_preference_score(course, slot.start.hour, features, state),
    }
    contributions = {key: _contribution(key, score, weights, config) for key, (score, _) in raw.items()}
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
    penalty = assess_course(course, slot, features).penalty
    total = config.ranker.score(contributions, {key: score for key, (score, _) in raw.items()}, penalty)
    return round(_clip(total), 2), factors, preference


# ---- v2: 5개 묶음 개인화 점수 ----

GROUP_LABELS = {
    "pet_fit": "반려견 특성 적합도",
    "user_preference": "사용자 선호도",
    "distance_time": "거리·시간 적합도",
    "weather_env": "날씨·환경 적합도",
    "feedback": "과거 산책 피드백",
}
GROUP_SOURCES = {
    "pet_fit": "반려견 프로필, 코스 데이터",
    "distance_time": "보호자 일정, 코스 예상 시간",
    "weather_env": "시간별 예보, 코스 데이터",
}
# 반려견 특성 묶음 안의 비중: 성향(익숙함, 혼잡, 기질) 절반, 활동량에 맞는 거리와 경사 절반
PET_FIT_SPLIT = {"personality": 0.5, "activity": 0.5}
DISTANCE_SIGMA = 0.35


BASE_GROUPS = ("pet_fit", "user_preference", "distance_time", "weather_env")


def feedback_strength(feedback_total: int, config: ScoringConfig = DEFAULT_CONFIG) -> float:
    """피드백 조정의 비중. 신규 사용자는 0이고, 쌓일수록 기준 가중치(15%)에 가까워진다."""
    if feedback_total <= 0:
        return 0.0
    return round(config.group_weights["feedback"] * feedback_total / (feedback_total + FEEDBACK_RAMP), 4)


def effective_group_weights(available: Mapping[str, bool], feedback_total: int, config: ScoringConfig = DEFAULT_CONFIG) -> dict[str, float]:
    """기본 4개 묶음은 데이터가 있는 것만 남겨 합이 1이 되게 다시 나눈다. 피드백은 조정 비중이다.

    피드백까지 가중합에 넣으면, 피드백이 없는 코스의 중립값 50이 다른 묶음(대부분 80~100점)보다 낮아
    피드백 1건만 남겨도 모든 코스의 점수가 4~5점씩 내려간다. 그래서 피드백은 중립값에서 벗어난 만큼만
    기본 적합도에 더한다(최대 ±기준 가중치 × 100점).
    """
    usable = {key: config.group_weights[key] for key in BASE_GROUPS if available.get(key, True) and config.group_weights[key] > 0}
    total = sum(usable.values())
    weights = {key: round(usable.get(key, 0.0) / total, 4) if total else 0.0 for key in BASE_GROUPS}
    weights["feedback"] = feedback_strength(feedback_total, config) if available.get("feedback", True) else 0.0
    return weights


def _distance_match(distance_km: float, preferred_km: float) -> float:
    return 100 * math.exp(-(math.log(distance_km / preferred_km) ** 2) / (2 * DISTANCE_SIGMA**2))


def user_preference_v2(
    course: CourseData,
    start_hour: int,
    features: PetFeatures,
    profile: LearnedProfile,
) -> tuple[float | None, tuple[str, ...], str]:
    """보호자가 입력한 선호 거리와 시간. 입력이 없으면 None이다.

    v1의 '선택 이력' 항목은 같은 방문이 익숙함과 과거 선호도에 이미 들어가 있어 뺐다. 산책 기록으로 배운
    거리는 여기가 아니라 반려견 특성 점수의 권장 거리를 보정하는 데 쓴다(profile.adjusted_ideal_km).
    """
    parts: list[float] = []
    evidence: list[str] = []
    sources: list[str] = []
    if features.preferred_distance_km:
        parts.append(_distance_match(course.distance_km, features.preferred_distance_km))
        evidence.append(f"선호 거리 {features.preferred_distance_km:g}km(보호자 입력), 이 코스 {course.distance_km:.1f}km")
        sources.append("보호자 입력")
    time_match = preferred_time_match(features.preferred_time_bucket, start_hour)
    if time_match is not None:
        parts.append(time_match)
        evidence.append(f"선호 시간대 {BUCKET_LABELS.get(features.preferred_time_bucket, '')}(보호자 입력), 추천 {start_hour}시")
        if "보호자 입력" not in sources:
            sources.append("보호자 입력")
    if not parts:
        return None, ("선호 거리와 시간이 없어 반영하지 않았어요",), ""
    return round(_clip(sum(parts) / len(parts)), 1), tuple(evidence), ", ".join(sources)


def feedback_score_v2(course: CourseData, state: PreferenceState) -> tuple[float, tuple[str, ...]]:
    """코스 피드백과 비슷한 코스에서 배운 특성 선호. v1의 익숙한 길 보너스와 반복 방문 감점은
    성향 점수의 익숙함에 이미 들어가 있어 뺐다."""
    current = state.courses.get(course.id, CoursePreference())
    prediction = predict_from_attributes(state.attribute_weights, course)
    if current.feedback_count and current.weight_total > 0:
        # v1은 이미 50 쪽으로 줄인 affinity를 한 번 더 줄였다. v2는 최근 가중 평균 신호를 한 번만 줄인다.
        signal = current.weighted_sum / current.weight_total
        confidence = current.weight_total / (current.weight_total + PRIOR_STRENGTH)
        score = confidence * signal + (1 - confidence) * prediction
        return round(_clip(score), 1), (f"이 코스 피드백 {current.feedback_count}회, 평균 만족 신호 {signal:.0f}점",)
    score = NEUTRAL + GENERALIZATION_DISCOUNT * (prediction - NEUTRAL)
    if abs(prediction - NEUTRAL) >= 1:
        direction = "비슷한 코스의 피드백이 좋았어요" if prediction > NEUTRAL else "비슷한 코스의 피드백이 낮았어요"
        return round(_clip(score), 1), (f"{direction} (예측 선호도 {prediction:.0f}점)",)
    return round(_clip(score), 1), ("이 코스와 비슷한 코스의 피드백이 아직 없어요",)


def schedule_v2(course: CourseData, slot: SlotEvaluation, schedule: Schedule, profile: LearnedProfile) -> tuple[float, tuple[str, ...]]:
    """희망 시간과 가능 시간에 맞는지. GPS 기록이 쌓였으면 이 반려견의 실제 걸음 속도로 예상 시간을 고친다."""
    expected = course.duration_min * (profile.pace_ratio or 1.0)
    target = schedule.preferred_duration_min
    if expected <= target:
        score = 100 - max(0.0, target * 0.5 - expected) / (target * 0.5) * 30
    else:
        score = 100 - (expected - target) / target * 120
    evidence = [f"희망 {target}분, 코스 약 {course.duration_min}분"]
    if profile.pace_ratio and abs(profile.pace_ratio - 1) >= 0.1:
        evidence.append(f"GPS 산책 {profile.pace_samples}회 기준 실제로는 약 {expected:.0f}분 걸려요")
    if not slot.fits_window:
        score *= 0.4
        evidence.append(f"가능 시간 {slot.window.end_hour}시를 넘겨요")
    return _clip(score), tuple(evidence)


def score_course_v2(
    course: CourseData,
    slot: SlotEvaluation,
    pet: PetProfile,
    features: PetFeatures,
    schedule: Schedule,
    state: PreferenceState,
    profile: LearnedProfile,
    weather_available: bool = True,
    config: ScoringConfig = DEFAULT_CONFIG,
) -> tuple[float, tuple[GroupScore, ...], tuple[FactorScore, ...], float]:
    """(개인화 점수, 묶음별 점수, 세부 항목, 과거 피드백 점수). 안전은 엔진이 앞 단계에서 따로 다룬다."""
    personality, personality_evidence = score_personality(course, pet, features, state)
    ideal_km, learned_share = adjusted_ideal_km(features.ideal_distance_km, profile)
    activity, activity_evidence = score_activity(course, replace(features, ideal_distance_km=ideal_km), slot)
    if learned_share:
        activity_evidence = (*activity_evidence, f"산책 {profile.completed_walks}회 기록으로 권장 거리를 {features.ideal_distance_km:.1f}km에서 {ideal_km:.1f}km로 보정")
    schedule_score, schedule_evidence = schedule_v2(course, slot, schedule, profile)
    weather, weather_evidence = score_weather(course, slot, features) if weather_available else (None, ("실제 날씨를 받지 못해 반영하지 않았어요",))
    preference, preference_evidence = feedback_score_v2(course, state)
    user_pref, user_evidence, user_source = user_preference_v2(course, slot.start.hour, features, profile)
    has_feedback = state.feedback_total > 0

    raw: dict[str, tuple[float | None, tuple[str, ...], str]] = {
        "pet_fit": (PET_FIT_SPLIT["personality"] * personality + PET_FIT_SPLIT["activity"] * activity, (*personality_evidence, *activity_evidence), GROUP_SOURCES["pet_fit"]),
        "user_preference": (user_pref, user_evidence, user_source),  # 보호자 입력만
        "distance_time": (schedule_score, schedule_evidence, GROUP_SOURCES["distance_time"]),
        "weather_env": (weather, weather_evidence, GROUP_SOURCES["weather_env"]),
        "feedback": (preference if has_feedback else None, preference_evidence if has_feedback else ("아직 피드백이 없어 반영하지 않았어요",), f"피드백 {state.feedback_total}건" if has_feedback else ""),
    }
    available = {key: score is not None for key, (score, _, _) in raw.items()}
    weights = effective_group_weights(available, state.feedback_total, config)

    def contribution(key: str, score: float | None) -> float:
        if score is None:
            return 0.0
        return weights[key] * 2 * (score - NEUTRAL) if key == "feedback" else weights[key] * score

    groups = tuple(
        GroupScore(
            key=key,
            label=GROUP_LABELS[key],
            score=None if score is None else round(score, 1),
            weight=weights[key],
            contribution=round(contribution(key, score), 2),
            evidence=evidence,
            available=available[key],
            source=source,
        )
        for key, (score, evidence, source) in raw.items()
    )
    total = sum(contribution(key, score) for key, (score, _, _) in raw.items())

    # 설명의 세부 근거용. 묶음 안의 비중을 나눠 기여도를 매긴다.
    detail_parts = (
        ("personality", personality, weights["pet_fit"] * PET_FIT_SPLIT["personality"], personality_evidence),
        ("activity", activity, weights["pet_fit"] * PET_FIT_SPLIT["activity"], activity_evidence),
        ("schedule", schedule_score, weights["distance_time"], schedule_evidence),
        ("weather", weather, weights["weather_env"], weather_evidence),
        ("preference", preference if has_feedback else None, weights["feedback"], preference_evidence),
        ("user_preference", user_pref, weights["user_preference"], user_evidence),
    )
    factors = tuple(
        FactorScore(
            key=key,
            label=FACTOR_LABELS[key],
            score=round(score, 1),
            weight=round(weight, 4),
            contribution=round(weight * 2 * (score - NEUTRAL) if key == "preference" else weight * score, 2),
            evidence=evidence,
        )
        for key, score, weight, evidence in detail_parts
        if score is not None
    )
    return round(_clip(total), 2), groups, factors, preference


def group_payload(groups: tuple[GroupScore, ...]) -> list[dict]:
    return [
        {
            "key": group.key,
            "label": group.label,
            "score": group.score,
            "weight": group.weight,
            "contribution": group.contribution,
            "evidence": list(group.evidence),
            "available": group.available,
            "source": group.source,
        }
        for group in groups
    ]
