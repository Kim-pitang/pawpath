"""추천 파이프라인.

1. 프로필 → 특성값
2. 가능 시간대 평가 → 추천 시간
3. 코스 × 출발 시각 평가 → 코스별 최적 시각과 총점
4. 상위 3개 선정, 학습 전 기준선과 비교, 설명 생성
"""
from collections.abc import Iterable, Mapping
from datetime import datetime

from app.recommender.config import DEFAULT_CONFIG, ScoringConfig
from app.recommender.course_scoring import adaptive_weights, score_course
from app.recommender.explain import build_explanation
from app.recommender.features import build_features
from app.recommender.safety import FORECAST, assess_course
from app.recommender.timeslots import candidate_starts, evaluate_slot, recommend_times
from app.recommender.types import (
    CourseData,
    CourseRecommendation,
    ExcludedCourse,
    FactorScore,
    HourWeather,
    PetFeatures,
    PetProfile,
    PreferenceState,
    RecommendationResult,
    SafetyAssessment,
    Schedule,
    SlotEvaluation,
)

TOP_N = 3
# 코스 총점이 비슷하면 시간대 점수(학습된 시간 선호 포함)가 높은 출발 시각을 고른다.
SLOT_TIEBREAK_WEIGHT = 0.15

INDOOR_ALTERNATIVES = (
    "간식을 숨겨 찾게 하는 노즈워크로 후각 활동을 시켜 주세요.",
    "터그 놀이나 짧은 기본 훈련으로 실내에서 에너지를 풀어 주세요.",
    "날씨가 나아지면 다시 추천을 받아 짧게 다녀오세요.",
)


def _best_for_course(
    course: CourseData,
    now: datetime,
    forecast: Mapping[datetime, HourWeather],
    pet: PetProfile,
    features: PetFeatures,
    schedule: Schedule,
    state: PreferenceState,
    config: ScoringConfig,
) -> tuple[tuple[float, SlotEvaluation, tuple[FactorScore, ...], float] | None, tuple[str, ...]]:
    """코스의 가장 좋은 출발 시각을 찾는다. 모든 시각이 위험하면 제외 이유를 돌려준다."""
    best = None
    best_key = float("-inf")
    weather_reasons: list[str] = []
    course_reasons: list[str] = []
    for start, window in candidate_starts(now, schedule.windows):
        slot = evaluate_slot(start, course.duration_min, window, forecast, features, state, now)
        if slot is None:
            continue
        if slot.unsafe_reason:
            weather_reasons.append(slot.unsafe_reason)
            continue
        blocked = assess_course(course, slot, features).blocked_reasons
        if blocked:
            course_reasons.extend(blocked)
            continue
        total, factors, preference = score_course(course, slot, pet, features, schedule, state, config)
        key = total + SLOT_TIEBREAK_WEIGHT * slot.score
        if key > best_key:
            best_key = key
            best = (total, slot, factors, preference)
    # 이 코스만의 이유가 있으면 그것을 알려 준다. 시간대별 더위처럼 모든 코스에 같은 이유는 하나만 남긴다.
    reasons = course_reasons or weather_reasons[:1]
    return best, tuple(dict.fromkeys(reasons))


def _rank_courses(
    courses: Iterable[CourseData],
    now: datetime,
    forecast: Mapping[datetime, HourWeather],
    pet: PetProfile,
    features: PetFeatures,
    schedule: Schedule,
    state: PreferenceState,
    config: ScoringConfig = DEFAULT_CONFIG,
    excluded: list[ExcludedCourse] | None = None,
) -> list[tuple[CourseData, float, SlotEvaluation, tuple[FactorScore, ...], float]]:
    scored = []
    for course in courses:
        if not course.pet_allowed:
            continue
        best, reasons = _best_for_course(course, now, forecast, pet, features, schedule, state, config)
        if best is not None:
            scored.append((course, *best))
        elif excluded is not None and reasons:
            excluded.append(ExcludedCourse(course=course, reasons=reasons))
    scored.sort(key=lambda item: (-item[1], item[0].id))
    return scored


LEVEL_ORDER = {"good": 0, "caution": 1, "danger": 2, "blocked": 3}
MEANINGFUL_SAFETY_GAP = 10.0


def _safer_alternative(chosen: CourseData, assessments: Mapping[int, SafetyAssessment], ranked: list[CourseData]) -> CourseData | None:
    """위험 수준이 실제로 낮은 코스 중 추천 점수가 가장 높은 코스. 비슷한 수준이면 권하지 않는다."""
    current = assessments[chosen.id]
    for course in ranked:
        if course.id == chosen.id:
            continue
        other = assessments[course.id]
        if LEVEL_ORDER[other.level] < LEVEL_ORDER[current.level] or other.score >= current.score + MEANINGFUL_SAFETY_GAP:
            return course
    return None


def recommend(
    pet: PetProfile,
    courses: Iterable[CourseData],
    forecast_hours: Iterable[HourWeather],
    schedule: Schedule,
    state: PreferenceState,
    now: datetime,
    config: ScoringConfig = DEFAULT_CONFIG,
    weather_source: str = FORECAST,
) -> RecommendationResult:
    course_list = list(courses)
    features = build_features(pet)
    forecast = {hour.time: hour for hour in forecast_hours}
    time_result = recommend_times(now, forecast, features, schedule, state)

    excluded: list[ExcludedCourse] = []
    ranked = _rank_courses(course_list, now, forecast, pet, features, schedule, state, config, excluded)
    # 같은 날씨에서 학습 상태만 비운 기준선. 이 차이가 곧 피드백 학습의 효과다.
    baseline = _rank_courses(course_list, now, forecast, pet, features, schedule, PreferenceState(), config)
    baseline_lookup = {item[0].id: (position, item[1]) for position, item in enumerate(baseline, start=1)}

    assessments = {item[0].id: assess_course(item[0], item[2], features, weather_source) for item in ranked}
    ranked_courses = [item[0] for item in ranked]

    recommendations = []
    for position, (course, total, slot, factors, preference) in enumerate(ranked[:TOP_N], start=1):
        baseline_rank, baseline_score = baseline_lookup.get(course.id, (position, total))
        assessment = assessments[course.id]
        alternative = None
        if assessment.level in ("caution", "danger"):
            alternative = _safer_alternative(course, assessments, ranked_courses)
        recommendations.append(
            CourseRecommendation(
                rank=position,
                course=course,
                slot=slot,
                total_score=total,
                baseline_score=baseline_score,
                baseline_rank=baseline_rank,
                factors=factors,
                explanation=build_explanation(pet, features, course, slot, factors, state),
                preference_score=preference,
                safety=assessment,
                alternative=alternative,
            )
        )

    blocked: list[str] = []
    if not recommendations:
        blocked = sorted(
            {slot.unsafe_reason for slot in time_result.all_slots if slot.unsafe_reason}
            | {reason for item in excluded for reason in item.reasons}
        )

    return RecommendationResult(
        walkable=bool(recommendations),
        features=features,
        time=time_result,
        courses=tuple(recommendations),
        weights=adaptive_weights(state.feedback_total, config),
        blocked_reasons=tuple(blocked),
        indoor_alternatives=INDOOR_ALTERNATIVES if not recommendations else (),
        excluded=tuple(excluded),
        ranker=config.ranker.name,
    )
