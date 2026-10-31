"""피드백 기반 온라인 학습.

세 가지 상태를 산책 피드백이 올 때마다 갱신한다.

1. 코스 친밀도: 최근 피드백에 더 큰 가중치를 두는 베이즈 축소 평균. 표본이 적을 때 극단값을 막는다.
2. 코스 특성 가중치: 정규화 LMS로 학습하는 선형 모델. 한 코스의 피드백이 비슷한 특성의
   다른 코스로 일반화되므로, 가 보지 않은 코스의 선호도도 예측할 수 있다.
3. 시간대 선호: 코스 친밀도와 같은 방식의 시간대별 평균.
"""
import math
from dataclasses import replace

from app.recommender.types import (
    BucketPreference,
    CourseData,
    CoursePreference,
    FeedbackInput,
    PetFeatures,
    PreferenceState,
)

NEUTRAL = 50.0
PRIOR_STRENGTH = 1.5
RECENCY_DECAY = 0.9
LMS_STEP = 0.3
# 가 보지 않은 코스는 예측을 일부만 반영한다. 한 코스의 평가가 비슷한 코스 전체를 끌고 가지 않게 한다.
GENERALIZATION_DISCOUNT = 0.4
DISLIKED_AFFINITY = 40.0
BAD_WEATHER_SAMPLE_WEIGHT = 0.5

ATTRIBUTE_LABELS = {
    "park": "공원",
    "lit": "밝은 길",
    "paved": "포장길",
    "quiet": "한적한 길",
    "shade": "그늘",
    "river": "강변",
    "forest": "숲길",
    "residential": "동네 골목",
    "short": "짧은 코스",
    "long": "긴 코스",
    "hill": "오르막",
}

TIME_BUCKETS = (
    ("morning", "오전", 5, 11),
    ("lunch", "점심", 11, 14),
    ("afternoon", "오후", 14, 18),
    ("evening", "저녁", 18, 24),
    ("night", "새벽", 0, 5),
)


def bucket_for_hour(hour: int) -> str:
    return next(key for key, _, start, end in TIME_BUCKETS if start <= hour < end)


def course_vector(course: CourseData) -> dict[str, float]:
    """코스 특성을 0~1 벡터로 나타낸다."""
    tags = set(course.scenery_tags)
    return {
        "park": float(course.has_park),
        "lit": {"good": 1.0, "partial": 0.6, "poor": 0.1, "unknown": 0.5}[course.lighting],
        "paved": float(course.is_paved),
        "quiet": {"low": 1.0, "medium": 0.5, "high": 0.0}[course.crowd_level],
        "shade": course.shade_level,
        "river": float("river" in tags),
        "forest": float("forest" in tags),
        "residential": float("residential" in tags),
        "short": 1.0 if course.distance_km <= 2.0 else 0.0,
        "long": 1.0 if course.distance_km >= 3.5 else 0.0,
        "hill": {"easy": 0.0, "moderate": 0.6, "hard": 1.0}[course.difficulty],
    }


def _centered(vector: dict[str, float]) -> dict[str, float]:
    return {key: value - 0.5 for key, value in vector.items()}


def predict_from_attributes(weights: dict[str, float], course: CourseData) -> float:
    """학습된 특성 가중치로 코스 선호도를 예측한다. 학습 전에는 중립값이다."""
    if not weights:
        return NEUTRAL
    x = _centered(course_vector(course))
    prediction = NEUTRAL + 100 * sum(weights.get(key, 0.0) * value for key, value in x.items())
    return max(0.0, min(100.0, prediction))


def feedback_signal(feedback: FeedbackInput) -> float:
    """피드백을 코스 만족 신호 0~100점으로 변환한다. 날씨 만족도는 코스 탓이 아니므로 뺀다."""
    pet = (feedback.pet_rating - 1) * 25
    walk = (feedback.walk_rating - 1) * 25
    revisit = 100.0 if feedback.would_revisit else 0.0
    difficulty = 100.0 if feedback.difficulty == "just_right" else 40.0
    return 0.5 * pet + 0.25 * walk + 0.2 * revisit + 0.05 * difficulty


def time_signal(feedback: FeedbackInput) -> float:
    """시간대 선호 신호. 시간대는 날씨 경험과 직결되므로 날씨 만족도를 포함한다."""
    pet = (feedback.pet_rating - 1) * 25
    walk = (feedback.walk_rating - 1) * 25
    weather = (feedback.weather_rating - 1) * 25
    return 0.5 * pet + 0.2 * walk + 0.3 * weather


def _shrunk_mean(weighted_sum: float, weight_total: float) -> float:
    return (PRIOR_STRENGTH * NEUTRAL + weighted_sum) / (PRIOR_STRENGTH + weight_total)


def _lms_update(weights: dict[str, float], course: CourseData, signal: float, sample_weight: float) -> dict[str, float]:
    x = _centered(course_vector(course))
    norm = sum(value * value for value in x.values()) or 1.0
    error = (signal - predict_from_attributes(weights, course)) / 100
    step = LMS_STEP * sample_weight * error / norm
    return {key: round(weights.get(key, 0.0) + step * x[key], 5) for key in x}


def record_visit(state: PreferenceState, course_id: int) -> PreferenceState:
    current = state.courses.get(course_id, CoursePreference())
    courses = {**state.courses, course_id: replace(current, visit_count=current.visit_count + 1)}
    return replace(state, courses=courses)


def apply_feedback(
    state: PreferenceState,
    course: CourseData,
    feedback: FeedbackInput,
    walk_hour: int,
) -> PreferenceState:
    """피드백 1건을 학습 상태에 반영한 새 상태를 돌려준다."""
    signal = feedback_signal(feedback)
    # 날씨가 나빴던 산책은 코스 평가에 덜 반영한다. 나쁜 경험이 코스 때문이 아닐 수 있다.
    sample_weight = BAD_WEATHER_SAMPLE_WEIGHT if feedback.weather_rating <= 2 else 1.0

    current = state.courses.get(course.id, CoursePreference())
    weighted_sum = RECENCY_DECAY * current.weighted_sum + sample_weight * signal
    weight_total = RECENCY_DECAY * current.weight_total + sample_weight
    updated_course = replace(
        current,
        weighted_sum=round(weighted_sum, 4),
        weight_total=round(weight_total, 4),
        affinity=round(_shrunk_mean(weighted_sum, weight_total), 2),
        feedback_count=current.feedback_count + 1,
    )

    bucket_key = bucket_for_hour(walk_hour)
    bucket = state.time_buckets.get(bucket_key, BucketPreference())
    updated_bucket = BucketPreference(
        weighted_sum=round(RECENCY_DECAY * bucket.weighted_sum + time_signal(feedback), 4),
        weight_total=round(RECENCY_DECAY * bucket.weight_total + 1, 4),
    )

    return PreferenceState(
        courses={**state.courses, course.id: updated_course},
        attribute_weights=_lms_update(state.attribute_weights, course, signal, sample_weight),
        time_buckets={**state.time_buckets, bucket_key: updated_bucket},
        feedback_total=state.feedback_total + 1,
    )


def time_bucket_score(state: PreferenceState, hour: int) -> float:
    bucket = state.time_buckets.get(bucket_for_hour(hour))
    if bucket is None:
        return NEUTRAL
    return _shrunk_mean(bucket.weighted_sum, bucket.weight_total)


def preference_score(
    course: CourseData,
    features: PetFeatures,
    state: PreferenceState,
) -> tuple[float, tuple[str, ...]]:
    """'과거 선호도' 항목 점수와 근거. 피드백이 없으면 정확히 중립값 50점이다."""
    current = state.courses.get(course.id, CoursePreference())
    attribute_prediction = predict_from_attributes(state.attribute_weights, course)
    evidence: list[str] = []

    if current.feedback_count:
        confidence = current.feedback_count / (current.feedback_count + PRIOR_STRENGTH)
        score = confidence * current.affinity + (1 - confidence) * attribute_prediction
        evidence.append(f"이 코스 피드백 {current.feedback_count}회 반영, 코스 선호도 {current.affinity:.0f}점")
    else:
        score = NEUTRAL + GENERALIZATION_DISCOUNT * (attribute_prediction - NEUTRAL)
        if state.attribute_weights and abs(attribute_prediction - NEUTRAL) >= 1:
            direction = "비슷한 코스의 피드백이 좋았어요" if attribute_prediction > NEUTRAL else "비슷한 코스의 피드백이 낮았어요"
            evidence.append(f"{direction} (예측 선호도 {attribute_prediction:.0f}점)")

    # 익숙한 길을 좋아하면 좋았던 코스에 가산, 새로운 길을 좋아하면 반복 방문에 감산한다.
    if features.novelty_tolerance < 0.4 and current.visit_count and current.feedback_count and current.affinity >= 60:
        bonus = min(12.0, 6.0 * current.visit_count)
        score += bonus
        evidence.append(f"익숙한 길을 좋아해 다시 가기 좋은 코스예요 (+{bonus:.0f}점)")
    elif features.novelty_tolerance > 0.6 and current.visit_count >= 3:
        penalty = min(15.0, 3.0 * (current.visit_count - 2))
        score -= penalty
        evidence.append(f"새로운 길을 좋아하는데 {current.visit_count}번 다녀온 코스예요 (-{penalty:.0f}점)")

    if not evidence:
        evidence.append("아직 피드백이 없어 중립값으로 계산했어요")
    return round(max(0.0, min(100.0, score)), 1), tuple(evidence)


BUCKET_ORDER = ("morning", "lunch", "afternoon", "evening")
BUCKET_LABELS = {key: label for key, label, _, _ in TIME_BUCKETS}


def preferred_time_match(preferred: str | None, hour: int) -> float | None:
    """선호 시간대와의 일치도. 입력이 없으면 None이다."""
    if preferred is None:
        return None
    bucket = bucket_for_hour(hour)
    if bucket == preferred:
        return 100.0
    if bucket in BUCKET_ORDER and preferred in BUCKET_ORDER and abs(BUCKET_ORDER.index(bucket) - BUCKET_ORDER.index(preferred)) == 1:
        return 60.0
    return 30.0


def user_preference_score(
    course: CourseData,
    start_hour: int,
    features: PetFeatures,
    state: PreferenceState,
) -> tuple[float, tuple[str, ...]]:
    """'사용자 선호도' 항목: 선호 거리, 선호 시간, 코스 선택 이력. 데이터가 없으면 중립값이다."""
    parts: list[float] = []
    evidence: list[str] = []

    if features.preferred_distance_km:
        ratio = course.distance_km / features.preferred_distance_km
        parts.append(100 * math.exp(-(math.log(ratio) ** 2) / (2 * 0.35**2)))
        evidence.append(f"선호 거리 {features.preferred_distance_km:g}km, 이 코스 {course.distance_km:.1f}km")

    time_match = preferred_time_match(features.preferred_time_bucket, start_hour)
    if time_match is not None:
        parts.append(time_match)
        evidence.append(f"선호 시간대 {BUCKET_LABELS.get(features.preferred_time_bucket, '')}, 추천 {start_hour}시")

    total_visits = sum(preference.visit_count for preference in state.courses.values())
    current = state.courses.get(course.id, CoursePreference())
    disliked = current.feedback_count > 0 and current.affinity < DISLIKED_AFFINITY
    # 낮게 평가한 코스는 자주 갔더라도 선호로 치지 않는다.
    if total_visits and not disliked:
        visits = current.visit_count
        share = visits / total_visits
        # 새로운 길을 좋아하는 아이일수록 지금까지의 선택 이력에 덜 묶이게 한다.
        parts.append(NEUTRAL + 40 * share * (1 - features.novelty_tolerance))
        if visits:
            evidence.append(f"지금까지 산책 {total_visits}번 중 {visits}번 선택")

    if not parts:
        return NEUTRAL, ("선호 거리와 시간을 입력하면 반영돼요",)
    return round(max(0.0, min(100.0, sum(parts) / len(parts))), 1), tuple(evidence) or ("선택 이력이 쌓이는 중이에요",)


def attribute_insights(weights: dict[str, float]) -> list[dict]:
    """학습된 특성 가중치를 사람이 읽을 수 있는 형태로 정리한다. 값이 클수록 선호한다."""
    items = [
        {"key": key, "label": label, "weight": round(weights.get(key, 0.0) * 100, 1)}
        for key, label in ATTRIBUTE_LABELS.items()
    ]
    return sorted(items, key=lambda item: -item["weight"])
