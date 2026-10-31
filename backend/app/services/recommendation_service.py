"""DB 모델과 추천 엔진을 잇는 서비스 계층."""
import logging
from collections import Counter
from datetime import datetime
from functools import lru_cache

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Pet, PetCoursePreference, Recommendation, User, WalkingCourse
from app.recommender.config import DEFAULT_CONFIG, ScoringConfig, parse_scoring_config
from app.recommender.course_scoring import LIGHTING_TEXT, score_breakdown
from app.recommender.engine import recommend
from app.recommender.explain import DISCLAIMER, hour_label
from app.recommender.safety import DEMO, FORECAST, assessment_payload
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
)
from app.services.llm_service import initial_engine_state
from app.services.weather_service import WeatherResult, find_record_id, get_weather

logger = logging.getLogger(__name__)


@lru_cache
def _parse_weights(raw: str) -> ScoringConfig:
    try:
        return parse_scoring_config(raw)
    except ValueError as exc:
        logger.warning("RECOMMENDER_WEIGHTS를 읽지 못해 기본 가중치를 씁니다: %s", exc)
        return DEFAULT_CONFIG


def scoring_config() -> ScoringConfig:
    return _parse_weights(get_settings().recommender_weights)


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


def to_course_data(course: WalkingCourse) -> CourseData:
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
        is_familiar=course.is_familiar,
        shade_level=course.shade_level,
        difficulty=course.difficulty,
        traffic_exposure=course.traffic_exposure,
        scenery_tags=tuple(course.scenery_tags),
        facility_counts=dict(Counter(facility["type"] for facility in course.facilities)),
        environment=course.environment or {},
        unknown=frozenset((course.data_sources or {}).get("unknown", [])),
    )


def to_schedule(user: User) -> Schedule:
    return Schedule(
        windows=windows_of(user),
        preferred_duration_min=user.preferred_duration_min,
        walks_per_day=user.walks_per_day,
    )


def windows_of(user: User) -> tuple[TimeWindow, ...]:
    return tuple(TimeWindow(w["start_hour"], w["end_hour"]) for w in user.available_windows)


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
        "score_breakdown": score_breakdown(item.factors),
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
        "reason": {"summary": item.explanation.summary, "details": list(item.explanation.details)},
        "cautions": list(item.explanation.cautions),
        "other_cautions": list(item.explanation.other_cautions),
    }


def _result_payload(
    result: RecommendationResult,
    weather: WeatherResult,
    courses_by_id: dict[int, WalkingCourse],
    pet: Pet,
    schedule: Schedule,
    state: PreferenceState,
) -> dict:
    features = result.features
    return {
        "pet_id": pet.id,
        "pet_name": pet.name,
        "walkable": result.walkable,
        "weather": {
            "source": weather.source,
            "scenario": weather.scenario,
            "is_mock": weather.is_mock,
            "notice": weather.notice,
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
        "explanation_engine": initial_engine_state() if result.courses else {"provider": "template", "model": None, "status": "disabled"},
        "blocked_reasons": list(result.blocked_reasons),
        "indoor_alternatives": list(result.indoor_alternatives),
        "disclaimer": DISCLAIMER,
    }


def create_recommendation(db: Session, pet: Pet, user: User, scenario: str, now: datetime) -> Recommendation:
    schedule = to_schedule(user)
    weather = get_weather(db, now, schedule.windows, scenario)
    state = load_state(db, pet)
    courses = active_courses(db, user)

    result = recommend(
        pet=to_profile(pet),
        courses=[to_course_data(course) for course in courses],
        forecast_hours=weather.hours,
        schedule=schedule,
        state=state,
        now=now,
        config=scoring_config(),
        weather_source=DEMO if weather.is_mock else FORECAST,
    )

    courses_by_id = {course.id: course for course in courses}
    payload = _result_payload(result, weather, courses_by_id, pet, schedule, state)
    top = result.courses[0] if result.courses else None
    record = Recommendation(
        pet_id=pet.id,
        top_course_id=top.course.id if top else None,
        weather_record_id=find_record_id(db, weather.source, top.slot.start.replace(minute=0)) if top else None,
        weather_source=weather.source,
        weather_scenario=weather.scenario,
        walkable=result.walkable,
        payload=payload,
        created_at=now,
    )
    db.add(record)
    db.commit()
    return record
