"""추천 파이프라인.

1. 프로필 → 특성값
2. 가능 시간대 평가 → 추천 시간
3. 코스 × 출발 시각 평가 → 코스별 최적 시각과 총점
4. 상위 3개 선정, 학습 전 기준선과 비교, 설명 생성

v2(기본)는 3, 4를 다음 네 단계로 나눈다. v1은 config.version이 rule-v1일 때 예전 그대로 동작한다.
  STEP 1 후보: 반려견 출입 가능, 가능 시간 안에 예보가 있는 코스
  STEP 2 안전: 위험 날씨와 차단 조건은 제외, 위험 수준은 개인화 점수와 관계없이 뒤로(safety_tier)
  STEP 3 개인화: 5개 묶음 가중합(course_scoring.score_course_v2) - 위험 감점 - 미선택 감점
  STEP 4 랭킹: 안전 단계, 점수 순. 경로가 겹치는 코스는 한 번만, 다녀온 코스만 남으면 새 코스 하나
"""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

from app.recommender.config import DEFAULT_CONFIG, V1, ScoringConfig
from app.recommender.course_scoring import adaptive_weights, effective_group_weights, score_course, score_course_v2
from app.recommender.diversity import DUPLICATE_OVERLAP, route_overlap
from app.recommender.explain import build_basis, build_explanation
from app.recommender.features import build_features
from app.recommender.profile import LearnedProfile, build_profile
from app.recommender.safety import FORECAST, UNAVAILABLE, assess_course, safety_tier
from app.recommender.timeslots import candidate_starts, evaluate_slot, recommend_times
from app.recommender.types import (
    CandidateScore,
    CourseData,
    CoursePreference,
    CourseRecommendation,
    ExcludedCourse,
    FactorScore,
    GroupScore,
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
    top_n: int = TOP_N,
) -> RecommendationResult:
    if config.version != V1:
        return _recommend_v2(pet, list(courses), list(forecast_hours), schedule, state, now, config, weather_source, top_n)
    return _recommend_v1(pet, courses, forecast_hours, schedule, state, now, config, weather_source, top_n)


def _recommend_v1(
    pet: PetProfile,
    courses: Iterable[CourseData],
    forecast_hours: Iterable[HourWeather],
    schedule: Schedule,
    state: PreferenceState,
    now: datetime,
    config: ScoringConfig,
    weather_source: str,
    top_n: int,
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
    for position, (course, total, slot, factors, preference) in enumerate(ranked[:top_n], start=1):
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
        algorithm_version=V1,
        status="ok" if recommendations else "unsafe",
    )


# ---- v2 ----

# 다른 코스를 걸은 날 하루에 1점, 최대 3점. 누르지 않은 것만으로는 깎지 않는다.
SKIP_PENALTY_PER_DAY = 1.0
MAX_SKIP_PENALTY = 3.0
# 다녀온 코스만 TOP 3에 남으면, 3위와 이 점수 차 안에 있는 새 코스로 3위를 바꾼다. 새 길을 좋아할수록 넓다.
EXPLORE_BASE_MARGIN = 3.0
EXPLORE_NOVELTY_MARGIN = 5.0

NO_FORECAST = "날씨 예보를 받지 못해 산책 시간을 평가하지 못했어요. 잠시 뒤 다시 추천받아 주세요."
NO_WINDOW = "지금부터 24시간 안에 산책 가능 시간이 없어요. 보호자 일정을 확인해 주세요."
NO_CANDIDATES = "반려견과 함께 걸을 수 있는 코스가 없어요."
WEATHER_UNAVAILABLE = "실제 날씨를 받지 못해 날씨는 점수에 넣지 않았어요. 안전 평가의 날씨 항목은 '확인 불가'로 표시했어요."


@dataclass(frozen=True)
class _Scored:
    course: CourseData
    slot: SlotEvaluation
    total: float
    personalization: float
    penalty: float
    skip: float
    groups: tuple[GroupScore, ...]
    factors: tuple[FactorScore, ...]
    preference: float
    assessment: SafetyAssessment
    tier: int


def _skip_penalty(course: CourseData, state: PreferenceState) -> float:
    return min(MAX_SKIP_PENALTY, SKIP_PENALTY_PER_DAY * state.skipped_days.get(course.id, 0))


def _best_slot_v2(
    course: CourseData,
    now: datetime,
    forecast: Mapping[datetime, HourWeather],
    pet: PetProfile,
    features: PetFeatures,
    schedule: Schedule,
    state: PreferenceState,
    profile: LearnedProfile,
    config: ScoringConfig,
    weather_source: str,
) -> tuple[_Scored | None, tuple[str, ...], bool]:
    """(최적 출발 시각의 평가, 제외 이유, 예보가 있었는지). 위험 수준이 낮은 시각을 먼저 고른다."""
    best: _Scored | None = None
    best_key: tuple[int, float] | None = None
    weather_reasons: list[str] = []
    course_reasons: list[str] = []
    evaluated = False
    for start, window in candidate_starts(now, schedule.windows):
        slot = evaluate_slot(start, course.duration_min, window, forecast, features, state, now)
        if slot is None:
            continue
        evaluated = True
        if slot.unsafe_reason:
            weather_reasons.append(slot.unsafe_reason)
            continue
        assessment = assess_course(course, slot, features, weather_source)
        if assessment.blocked_reasons:
            course_reasons.extend(assessment.blocked_reasons)
            continue
        personalization, groups, factors, preference = score_course_v2(
            course, slot, pet, features, schedule, state, profile, weather_source != UNAVAILABLE, config
        )
        skip = _skip_penalty(course, state)
        contributions = {group.key: group.contribution for group in groups}
        scores = {group.key: group.score or 0.0 for group in groups}
        # 기본 적합도 + 피드백 조정 - 위험 감점 - 미선택 감점. 순위 모델을 바꿔 끼울 수 있게 Ranker로 계산한다.
        total = round(max(0.0, min(100.0, config.ranker.score(contributions, scores, assessment.penalty + skip))), 2)
        tier = safety_tier(assessment)
        key = (tier, -(total + SLOT_TIEBREAK_WEIGHT * slot.score))
        if best_key is None or key < best_key:
            best_key = key
            best = _Scored(course, slot, total, personalization, assessment.penalty, skip, groups, factors, preference, assessment, tier)
    reasons = course_reasons or weather_reasons[:1]
    return best, tuple(dict.fromkeys(reasons)), evaluated


def _rank_v2(courses, now, forecast, pet, features, schedule, state, profile, config, weather_source):
    """(순위순 후보, 제외 코스, 예보로 평가한 코스가 있었는지)"""
    scored: list[_Scored] = []
    excluded: list[ExcludedCourse] = []
    evaluated_any = False
    for course in courses:
        if not course.pet_allowed:
            continue
        best, reasons, evaluated = _best_slot_v2(course, now, forecast, pet, features, schedule, state, profile, config, weather_source)
        evaluated_any = evaluated_any or evaluated
        if best is not None:
            scored.append(best)
        elif reasons:
            excluded.append(ExcludedCourse(course=course, reasons=reasons))
    scored.sort(key=lambda item: (item.tier, -item.total, item.course.id))
    return scored, excluded, evaluated_any


def _duplicate_of(item: _Scored, picked: list[_Scored]) -> _Scored | None:
    return next((other for other in picked if route_overlap(item.course.route, other.course.route) >= DUPLICATE_OVERLAP), None)


def _visited(course: CourseData, state: PreferenceState) -> bool:
    return state.courses.get(course.id, CoursePreference()).visit_count > 0


def _select(scored: list[_Scored], state: PreferenceState, features: PetFeatures, top_n: int = TOP_N) -> tuple[list[_Scored], dict[int, int], dict[int, str], int | None]:
    """상위 코스 고르기. (고른 코스, 중복으로 미룬 코스 → 겹친 코스, 다른 후보가 없어 함께 올린 중복 → 겹친 코스 이름, 탐색 코스)"""
    picked: list[_Scored] = []
    duplicates: dict[int, int] = {}
    for item in scored:
        if len(picked) == top_n:
            break
        other = _duplicate_of(item, picked)
        if other is not None:
            duplicates[item.course.id] = other.course.id
            continue
        picked.append(item)

    # 후보가 모자라면 없는 코스를 만들지 않고, 미뤄 둔 중복 코스를 겹친다고 알리며 채운다.
    similar: dict[int, str] = {}
    by_id = {item.course.id: item for item in scored}
    for item in scored:
        if len(picked) >= top_n:
            break
        if item.course.id in duplicates and item not in picked:
            picked.append(item)
            similar[item.course.id] = by_id[duplicates[item.course.id]].course.name
    picked.sort(key=lambda item: (item.tier, -item.total, item.course.id))

    explore = None
    if len(picked) == top_n and all(_visited(item.course, state) for item in picked):
        third = picked[-1]
        margin = EXPLORE_BASE_MARGIN + EXPLORE_NOVELTY_MARGIN * features.novelty_tolerance
        for item in scored:
            if item in picked or _visited(item.course, state) or item.tier > third.tier or item.total < third.total - margin:
                continue
            if _duplicate_of(item, picked[:-1]) is not None:
                continue
            picked[-1] = item
            explore = item.course.id
            break
    return picked, duplicates, similar, explore


def _candidate_log(scored, excluded, picked, duplicates, explore) -> tuple[CandidateScore, ...]:
    ranks = {item.course.id: rank for rank, item in enumerate(picked, start=1)}
    rows = [
        CandidateScore(
            course_id=item.course.id,
            rank=ranks.get(item.course.id),
            position=position,
            total_score=item.total,
            personalization_score=item.personalization,
            safety_penalty=item.penalty,
            skip_penalty=item.skip,
            safety_level=item.assessment.level,
            safety_score=item.assessment.score,
            groups={group.key: {"score": group.score, "weight": group.weight} for group in item.groups},
            data_quality=item.assessment.data_quality,
            duplicate_of=duplicates.get(item.course.id),
            exploration=item.course.id == explore,
        )
        for position, item in enumerate(scored, start=1)
    ]
    rows.extend(
        CandidateScore(
            course_id=item.course.id, rank=None, position=None, total_score=None, personalization_score=None,
            safety_penalty=0.0, skip_penalty=0.0, safety_level="blocked", safety_score=None, groups={}, data_quality={},
            excluded_reasons=item.reasons,
        )
        for item in excluded
    )
    return tuple(rows)


def _recommend_v2(
    pet: PetProfile,
    course_list: list[CourseData],
    forecast_hours: list[HourWeather],
    schedule: Schedule,
    state: PreferenceState,
    now: datetime,
    config: ScoringConfig,
    weather_source: str,
    top_n: int,
) -> RecommendationResult:
    features = build_features(pet)
    forecast = {hour.time: hour for hour in forecast_hours}
    profile = build_profile(state.walks)
    time_result = recommend_times(now, forecast, features, schedule, state)

    # STEP 1~3: 후보마다 안전을 먼저 보고 개인화 점수를 매긴다.
    scored, excluded, evaluated = _rank_v2(course_list, now, forecast, pet, features, schedule, state, profile, config, weather_source)
    # 같은 날씨에서 학습 상태만 비운 기준선. 보호자가 입력한 선호는 그대로 둔다.
    baseline, _, _ = _rank_v2(course_list, now, forecast, pet, features, schedule, PreferenceState(), LearnedProfile(), config, weather_source)
    baseline_picked, _, _, _ = _select(baseline, PreferenceState(), features, top_n)
    baseline_ranks = {item.course.id: rank for rank, item in enumerate(baseline_picked, start=1)}
    baseline_scores = {item.course.id: item.total for item in baseline}

    # STEP 4: 최종 랭킹
    picked, duplicates, similar, explore = _select(scored, state, features, top_n)
    assessments = {item.course.id: item.assessment for item in scored}
    ranked_courses = [item.course for item in scored]
    weather_available = weather_source != UNAVAILABLE

    recommendations = []
    for rank, item in enumerate(picked, start=1):
        alternative = None
        if item.assessment.level in ("caution", "danger"):
            alternative = _safer_alternative(item.course, assessments, ranked_courses)
        explanation = build_explanation(
            pet, features, item.course, item.slot, item.factors, state,
            weather_available=weather_available,
            exploration=item.course.id == explore,
            similar_to=similar.get(item.course.id),
            basis=build_basis(pet, features, item.course, item.slot, item.groups, item.assessment, state, profile, weather_source),
        )
        recommendations.append(
            CourseRecommendation(
                rank=rank,
                course=item.course,
                slot=item.slot,
                total_score=item.total,
                baseline_score=baseline_scores.get(item.course.id, item.total),
                # 기준선 TOP 3 밖이었다면 TOP 3 바로 다음 순위로 본다.
                baseline_rank=baseline_ranks.get(item.course.id, len(baseline_picked) + 1),
                factors=item.factors,
                explanation=explanation,
                preference_score=item.preference,
                safety=item.assessment,
                alternative=alternative,
                personalization_score=item.personalization,
                safety_penalty=item.penalty,
                skip_penalty=item.skip,
                groups=item.groups,
                exploration=item.course.id == explore,
                similar_to=similar.get(item.course.id),
            )
        )

    if recommendations:
        status = "ok"
    elif not any(course.pet_allowed for course in course_list):
        status = "no_candidates"
    elif not candidate_starts(now, schedule.windows):
        status = "no_window"
    elif not evaluated:
        status = "no_forecast"
    else:
        status = "unsafe"

    blocked: list[str] = []
    if status == "unsafe":
        blocked = sorted(
            {slot.unsafe_reason for slot in time_result.all_slots if slot.unsafe_reason}
            | {reason for item in excluded for reason in item.reasons}
        )
    elif status != "ok":
        blocked = [{"no_candidates": NO_CANDIDATES, "no_window": NO_WINDOW, "no_forecast": NO_FORECAST}[status]]

    available = {
        "user_preference": bool(features.preferred_distance_km or features.preferred_time_bucket),
        "weather_env": weather_available,
        "feedback": state.feedback_total > 0,
    }
    return RecommendationResult(
        walkable=bool(recommendations),
        features=features,
        time=time_result,
        courses=tuple(recommendations),
        weights=effective_group_weights(available, state.feedback_total, config),
        blocked_reasons=tuple(blocked),
        indoor_alternatives=INDOOR_ALTERNATIVES if status in ("unsafe", "no_forecast") else (),
        excluded=tuple(excluded),
        ranker=config.ranker.name,
        algorithm_version=config.version,
        status=status,
        data_notice=NO_FORECAST if status == "no_forecast" else (WEATHER_UNAVAILABLE if not weather_available else None),
        candidates=_candidate_log(scored, excluded, picked, duplicates, explore),
    )
