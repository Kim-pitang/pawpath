"""추천 파이프라인.

1. 프로필 → 특성값
2. 가능 시간대 평가 → 추천 시간
3. 코스 × 출발 시각 평가 → 코스별 최적 시각과 총점
4. 상위 3개 선정, 학습 전 기준선과 비교, 설명 생성
"""
from collections.abc import Iterable, Mapping
from datetime import datetime

from app.recommender.course_scoring import adaptive_weights, score_course
from app.recommender.explain import build_explanation
from app.recommender.features import build_features
from app.recommender.timeslots import candidate_starts, evaluate_slot, recommend_times
from app.recommender.types import (
    CourseData,
    CourseRecommendation,
    FactorScore,
    HourWeather,
    PetFeatures,
    PetProfile,
    PreferenceState,
    RecommendationResult,
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
) -> tuple[float, SlotEvaluation, tuple[FactorScore, ...], float] | None:
    best = None
    best_key = float("-inf")
    for start, window in candidate_starts(now, schedule.windows):
        slot = evaluate_slot(start, course.duration_min, window, forecast, features, state, now)
        if slot is None or slot.unsafe_reason:
            continue
        total, factors, preference = score_course(course, slot, pet, features, schedule, state)
        key = total + SLOT_TIEBREAK_WEIGHT * slot.score
        if key > best_key:
            best_key = key
            best = (total, slot, factors, preference)
    return best


def _rank_courses(
    courses: Iterable[CourseData],
    now: datetime,
    forecast: Mapping[datetime, HourWeather],
    pet: PetProfile,
    features: PetFeatures,
    schedule: Schedule,
    state: PreferenceState,
) -> list[tuple[CourseData, float, SlotEvaluation, tuple[FactorScore, ...], float]]:
    scored = []
    for course in courses:
        if not course.pet_allowed:
            continue
        best = _best_for_course(course, now, forecast, pet, features, schedule, state)
        if best is not None:
            scored.append((course, *best))
    scored.sort(key=lambda item: (-item[1], item[0].id))
    return scored


def recommend(
    pet: PetProfile,
    courses: Iterable[CourseData],
    forecast_hours: Iterable[HourWeather],
    schedule: Schedule,
    state: PreferenceState,
    now: datetime,
) -> RecommendationResult:
    course_list = list(courses)
    features = build_features(pet)
    forecast = {hour.time: hour for hour in forecast_hours}
    time_result = recommend_times(now, forecast, features, schedule, state)

    ranked = _rank_courses(course_list, now, forecast, pet, features, schedule, state)
    # 같은 날씨에서 학습 상태만 비운 기준선. 이 차이가 곧 피드백 학습의 효과다.
    baseline = _rank_courses(course_list, now, forecast, pet, features, schedule, PreferenceState())
    baseline_lookup = {item[0].id: (position, item[1]) for position, item in enumerate(baseline, start=1)}

    recommendations = []
    for position, (course, total, slot, factors, preference) in enumerate(ranked[:TOP_N], start=1):
        baseline_rank, baseline_score = baseline_lookup.get(course.id, (position, total))
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
            )
        )

    blocked: list[str] = []
    if not recommendations:
        blocked = sorted({slot.unsafe_reason for slot in time_result.all_slots if slot.unsafe_reason})

    return RecommendationResult(
        walkable=bool(recommendations),
        features=features,
        time=time_result,
        courses=tuple(recommendations),
        weights=adaptive_weights(state.feedback_total),
        blocked_reasons=tuple(blocked),
        indoor_alternatives=INDOOR_ALTERNATIVES if not recommendations else (),
    )
