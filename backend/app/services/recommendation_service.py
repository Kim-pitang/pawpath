"""DB 모델과 추천 엔진을 잇는 서비스 계층."""
import logging
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timedelta
from functools import lru_cache

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Pet, PetCoursePreference, Profile, Recommendation, RecommendationItem, User, WalkHistory, WalkingCourse
from app.recommender.config import BASE_WEIGHTS, DEFAULT_CONFIG, LEGACY_CONFIG, V1, VERSIONS, ScoringConfig, parse_scoring_config
from app.recommender.course_scoring import LIGHTING_TEXT, group_payload, score_breakdown
from app.recommender.engine import recommend
from app.recommender.explain import DISCLAIMER, hour_label
from app.recommender.safety import DEMO, FORECAST, UNAVAILABLE, assessment_payload
from app.recommender.types import (
    BucketPreference,
    CourseData,
    CoursePreference,
    CourseRecommendation,
    PetProfile,
    PreferenceState,
    RecommendationResult,
    Schedule,
    SlotEvaluation,
    TimeWindow,
    WalkSample,
)
from app.seed import DEFAULT_USER_ID
from app.services.llm_service import initial_engine_state
from app.services.weather_service import MOCK_FALLBACK, WeatherResult, find_record_id, get_weather

logger = logging.getLogger(__name__)


# 최근 추천을 다른 코스를 걸은 날과 맞춰 볼 기간
SKIP_LOOKBACK_DAYS = 14


@lru_cache
def _parse_weights(raw: str, version: str) -> ScoringConfig:
    algorithm = VERSIONS.get(version)
    if algorithm is None:
        logger.warning("RECOMMENDER_VERSION을 알 수 없어 v2를 씁니다: %s", version)
        algorithm = DEFAULT_CONFIG.version
    try:
        return parse_scoring_config(raw, algorithm)
    except ValueError as exc:
        logger.warning("RECOMMENDER_WEIGHTS를 읽지 못해 기본 가중치를 씁니다: %s", exc)
        return LEGACY_CONFIG if algorithm == V1 else DEFAULT_CONFIG


def scoring_config() -> ScoringConfig:
    settings = get_settings()
    return _parse_weights(settings.recommender_weights, settings.recommender_version)


def weather_source_of(weather: WeatherResult) -> str:
    """안전 평가에 쓸 날씨 출처. API 장애로 대신 쓴 모의 날씨는 실제 날씨가 아니므로 '확인 불가'다."""
    if weather.source == MOCK_FALLBACK:
        return UNAVAILABLE
    return DEMO if weather.is_mock else FORECAST


def to_profile(pet: Pet) -> PetProfile:
    return PetProfile(
        name=pet.name,
        age_years=pet.age_years,
        weight_kg=pet.weight_kg,
        size=pet.size,
        activity_level=pet.activity_level,
        personality=pet.personality,
        path_preference=pet.path_preference,
        heat_sensitivity=pet.heat_sensitivity,
        novelty_reaction=pet.novelty_reaction,
        preferred_distance_km=pet.preferred_distance_km,
        preferred_time_bucket=pet.preferred_time_bucket,
    )


def visible_to(user: User | None):
    """공용 코스와, 이 보호자의 내 산책길 코스. 다른 보호자의 코스는 보이지 않는다."""
    if user is None:
        return WalkingCourse.owner_user_id.is_(None)
    return or_(WalkingCourse.owner_user_id.is_(None), WalkingCourse.owner_user_id == user.id)


def active_courses(db: Session, user: User | None) -> list[WalkingCourse]:
    """지금 서비스 지역에서 추천 후보로 쓰는 코스. 멀리 떨어진 지역의 코스가 추천에 섞이지 않게 한다."""
    area = get_settings().service_area_label
    query = select(WalkingCourse).where(WalkingCourse.area == area, WalkingCourse.is_active.is_not(False), visible_to(user))
    return list(db.scalars(query.order_by(WalkingCourse.id)))


def to_course_data(course: WalkingCourse, trust_familiar: bool = True) -> CourseData:
    """trust_familiar가 거짓이면 시드 코스의 '집 근처 코스' 표시를 쓰지 않는다.

    이 표시는 시연 보호자가 사는 동네를 가정해 팀이 붙인 값이라, 다른 보호자에게는 근거가 없다.
    내 산책길 코스의 익숙함은 실제로 걸은 기록이므로 그대로 쓴다.
    """
    return CourseData(
        id=course.id,
        name=course.name,
        distance_km=course.distance_km,
        duration_min=course.duration_min,
        has_park=course.has_park,
        lighting=course.lighting,
        is_paved=course.is_paved,
        crowd_level=course.crowd_level,
        pet_allowed=course.pet_allowed,
        is_familiar=course.is_familiar and (trust_familiar or course.is_personal),
        shade_level=course.shade_level,
        difficulty=course.difficulty,
        traffic_exposure=course.traffic_exposure,
        scenery_tags=tuple(course.scenery_tags),
        facility_counts=dict(Counter(facility["type"] for facility in course.facilities)),
        environment=course.environment or {},
        unknown=frozenset((course.data_sources or {}).get("unknown", [])),
        route=tuple((point[0], point[1]) for point in (course.route or [])),
    )


def to_schedule(owner: User | Profile) -> Schedule:
    return Schedule(
        windows=windows_of(owner),
        preferred_duration_min=owner.preferred_duration_min,
        walks_per_day=owner.walks_per_day,
    )


def windows_of(owner: User | Profile) -> tuple[TimeWindow, ...]:
    return tuple(TimeWindow(w["start_hour"], w["end_hour"]) for w in owner.available_windows)


def load_state(db: Session, pet: Pet) -> PreferenceState:
    rows = db.scalars(select(PetCoursePreference).where(PetCoursePreference.pet_id == pet.id))
    return PreferenceState(
        courses={
            row.course_id: CoursePreference(
                affinity=row.affinity,
                weighted_sum=row.weighted_sum,
                weight_total=row.weight_total,
                visit_count=row.visit_count,
                feedback_count=row.feedback_count,
            )
            for row in rows
        },
        attribute_weights=dict(pet.learned_attribute_weights or {}),
        time_buckets={
            key: BucketPreference(**value) for key, value in (pet.learned_time_buckets or {}).items()
        },
        feedback_total=pet.feedback_total,
    )


def load_behavior(db: Session, pet: Pet, now: datetime) -> tuple[tuple[WalkSample, ...], dict[int, int]]:
    """v2가 쓰는 행동 기록: 산책 표본과, 추천 TOP 3에 있었지만 그날 다른 코스를 걸은 날 수."""
    walks = list(db.scalars(select(WalkHistory).where(WalkHistory.pet_id == pet.id).order_by(WalkHistory.started_at)))
    samples = tuple(
        WalkSample(
            course_id=walk.course_id,
            distance_km=walk.distance_km if walk.distance_km is not None else walk.course.distance_km,
            expected_min=walk.course.duration_min,
            actual_min=walk.duration_min,
            start_hour=walk.started_at.hour,
            tracking_source=walk.tracking_source or "manual",
            signal=walk.feedback.signal if walk.feedback else None,
            difficulty=walk.feedback.difficulty if walk.feedback else None,
        )
        for walk in walks
    )

    # 오늘은 아직 고르는 중일 수 있어 어제까지만 본다. 누르지 않은 것만으로는 세지 않는다.
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = today - timedelta(days=SKIP_LOOKBACK_DAYS)
    walked: dict = defaultdict(set)
    for walk in walks:
        if since <= walk.started_at < today and walk.tracking_source != "simulation":
            walked[walk.started_at.date()].add(walk.course_id)
    shown: dict = defaultdict(set)
    records = db.scalars(
        select(Recommendation).where(Recommendation.pet_id == pet.id, Recommendation.walkable.is_(True), Recommendation.created_at >= since, Recommendation.created_at < today)
    )
    for record in records:
        shown[record.created_at.date()].update(course["course_id"] for course in record.payload.get("courses", []))
    skipped: Counter = Counter()
    for day, course_ids in shown.items():
        if walked.get(day):
            skipped.update(course_ids - walked[day])
    return samples, dict(skipped)


def _slot_payload(slot: SlotEvaluation) -> dict:
    weather = slot.weather
    return {
        "start": slot.start.isoformat(),
        "end": slot.end.isoformat(),
        "label": hour_label(slot.start.hour),
        "duration_min": slot.duration_min,
        "score": slot.score,
        "components": slot.components,
        "excluded_reason": slot.unsafe_reason,
        "before_rain": slot.before_rain,
        "rain_onset": slot.rain_onset.isoformat() if slot.rain_onset else None,
        "rain_overlap_min": slot.rain_overlap_min,
        "is_dark": slot.is_dark,
        "fits_window": slot.fits_window,
        "weather": {
            "temperature": weather.temperature,
            "apparent_temperature": weather.apparent_temperature,
            "precipitation_probability": weather.precipitation_probability,
            "precipitation_mm": weather.precipitation_mm,
            "humidity": weather.humidity,
            "wind_speed": weather.wind_speed,
            "uv_index": weather.uv_index,
        },
    }


def _safety_payload(course: WalkingCourse) -> dict:
    counts = Counter(facility["type"] for facility in course.facilities)
    return {
        "lighting": course.lighting,
        "lighting_text": LIGHTING_TEXT[course.lighting],
        "lighting_is_estimate": True,
        "has_park": course.has_park,
        "park_names": course.park_names,
        "is_paved": course.is_paved,
        "surface_note": course.surface_note,
        "traffic_exposure": course.traffic_exposure,
        "crowd_level": course.crowd_level,
        "pet_allowed": course.pet_allowed,
        "pet_rule_note": course.pet_rule_note,
        "verified_facilities": dict(counts),
        "is_personal": course.is_personal,
        "unknown": list((course.data_sources or {}).get("unknown", [])),
    }


def _alternative_payload(item: CourseRecommendation) -> dict | None:
    if item.alternative is None:
        return None
    return {"course_id": item.alternative.id, "name": item.alternative.name, "distance_km": item.alternative.distance_km, "duration_min": item.alternative.duration_min}


def _course_payload(item: CourseRecommendation, course: WalkingCourse, state: PreferenceState) -> dict:
    preference = state.courses.get(course.id, CoursePreference())
    return {
        "rank": item.rank,
        "course_id": course.id,
        "code": course.code,
        "name": course.name,
        "description": course.description,
        "is_personal": course.is_personal,
        "distance_km": course.distance_km,
        "duration_min": course.duration_min,
        "total_score": item.total_score,
        "baseline_score": item.baseline_score,
        "learning_delta": round(item.total_score - item.baseline_score, 2),
        "baseline_rank": item.baseline_rank,
        "rank_change": item.baseline_rank - item.rank,
        "preference_score": item.preference_score,
        "visit_count": preference.visit_count,
        "feedback_count": preference.feedback_count,
        "recommended_time": _slot_payload(item.slot),
        "safety": _safety_payload(course),
        "safety_assessment": assessment_payload(item.safety),
        "alternative": _alternative_payload(item),
        # v2는 데이터가 있는 묶음만 보여 주고, 반영하지 않은 묶음은 score_groups에 남긴다.
        "score_breakdown": [group for group in group_payload(item.groups) if group["available"]] if item.groups else score_breakdown(item.factors),
        "factors": [
            {
                "key": factor.key,
                "label": factor.label,
                "score": factor.score,
                "weight": factor.weight,
                "contribution": factor.contribution,
                "evidence": list(factor.evidence),
            }
            for factor in item.factors
        ],
        "reason": {"summary": item.explanation.summary, "details": list(item.explanation.details), "basis": list(item.explanation.basis)},
        "cautions": list(item.explanation.cautions),
        "other_cautions": list(item.explanation.other_cautions),
        "personalization_score": item.personalization_score,
        "safety_penalty": item.safety_penalty,
        "skip_penalty": item.skip_penalty,
        "score_groups": group_payload(item.groups),
        "exploration": item.exploration,
        "similar_to": item.similar_to,
    }


def _result_payload(
    result: RecommendationResult,
    weather: WeatherResult,
    courses_by_id: dict[int, WalkingCourse],
    pet: Pet,
    schedule: Schedule,
    state: PreferenceState,
    config: ScoringConfig = DEFAULT_CONFIG,
) -> dict:
    features = result.features
    return {
        "pet_id": pet.id,
        "pet_name": pet.name,
        "walkable": result.walkable,
        "status": result.status,
        "data_notice": result.data_notice,
        "algorithm": {
            "version": result.algorithm_version,
            "ranker": result.ranker,
            "base_weights": dict(BASE_WEIGHTS if result.algorithm_version == V1 else config.group_weights),
        },
        "weather": {
            "source": weather.source,
            "scenario": weather.scenario,
            "is_mock": weather.is_mock,
            "notice": weather.notice,
            "fetched_at": weather.fetched_at.isoformat() if weather.fetched_at else None,
            "is_available": weather.source != MOCK_FALLBACK,
        },
        "features": {
            "life_stage": features.life_stage,
            "ideal_walk_min": features.ideal_walk_min,
            "ideal_distance_km": features.ideal_distance_km,
            "novelty_tolerance": features.novelty_tolerance,
            "crowd_tolerance": features.crowd_tolerance,
            "comfort_low": features.comfort_low,
            "comfort_high": features.comfort_high,
        },
        "schedule": {
            "windows": [{"start_hour": w.start_hour, "end_hour": w.end_hour} for w in schedule.windows],
            "preferred_duration_min": schedule.preferred_duration_min,
            "walks_per_day": schedule.walks_per_day,
        },
        "time_recommendation": {
            "recommended_duration_min": result.time.recommended_duration_min,
            "best_slots": [_slot_payload(slot) for slot in result.time.best_slots],
            "slots": [_slot_payload(slot) for slot in result.time.all_slots],
        },
        "courses": [_course_payload(item, courses_by_id[item.course.id], state) for item in result.courses],
        "weights": {key: round(value, 4) for key, value in result.weights.items()},
        "learning": {
            "feedback_total": state.feedback_total,
            "is_personalized": state.feedback_total > 0,
            "mode": "personalized" if state.feedback_total > 0 else "rule_based",
            "ranker": result.ranker,
        },
        "excluded_courses": [
            {"course_id": item.course.id, "name": item.course.name, "reasons": list(item.reasons)}
            for item in result.excluded
        ],
        # 날씨를 확인하지 못했으면 LLM에 줄 근거가 사실이 아니므로 계산 결과 문장만 쓴다.
        "explanation_engine": initial_engine_state() if result.courses and weather.source != MOCK_FALLBACK else {"provider": "template", "model": None, "status": "disabled"},
        "blocked_reasons": list(result.blocked_reasons),
        "indoor_alternatives": list(result.indoor_alternatives),
        "disclaimer": DISCLAIMER,
    }


def create_recommendation(db: Session, pet: Pet, user: User, scenario: str, now: datetime, profile: Profile | None = None) -> Recommendation:
    """추천을 계산해 저장한다. 프로필을 주면 그 프로필의 일정으로 계산하고 받은 사람으로 남긴다."""
    schedule = to_schedule(profile or user)
    weather = get_weather(db, now, schedule.windows, scenario)
    walks, skipped_days = load_behavior(db, pet, now)
    state = replace(load_state(db, pet), walks=walks, skipped_days=skipped_days)
    courses = active_courses(db, user)
    config = scoring_config()

    result = recommend(
        pet=to_profile(pet),
        courses=[to_course_data(course, trust_familiar=user.id == DEFAULT_USER_ID) for course in courses],
        forecast_hours=weather.hours,
        schedule=schedule,
        state=state,
        now=now,
        config=config,
        weather_source=weather_source_of(weather),
    )

    courses_by_id = {course.id: course for course in courses}
    payload = _result_payload(result, weather, courses_by_id, pet, schedule, state, config)
    top = result.courses[0] if result.courses else None
    record = Recommendation(
        pet_id=pet.id,
        profile_id=profile.id if profile else None,
        top_course_id=top.course.id if top else None,
        weather_record_id=find_record_id(db, weather.source, top.slot.start.replace(minute=0)) if top else None,
        weather_source=weather.source,
        weather_scenario=weather.scenario,
        walkable=result.walkable,
        payload=payload,
        created_at=now,
        algorithm_version=result.algorithm_version,
        weather_fetched_at=weather.fetched_at,
    )
    db.add(record)
    db.flush()
    db.add_all(
        RecommendationItem(
            recommendation_id=record.id,
            pet_id=pet.id,
            course_id=item.course_id,
            algorithm_version=result.algorithm_version,
            rank=item.rank,
            position=item.position,
            total_score=item.total_score,
            personalization_score=item.personalization_score,
            safety_penalty=item.safety_penalty,
            skip_penalty=item.skip_penalty,
            safety_level=item.safety_level,
            safety_score=item.safety_score,
            group_scores=item.groups,
            data_quality=item.data_quality,
            excluded_reasons=list(item.excluded_reasons),
            duplicate_of=item.duplicate_of,
            exploration=item.exploration,
            created_at=now,
        )
        for item in result.candidates
    )
    db.commit()
    return record
