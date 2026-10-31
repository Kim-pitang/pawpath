"""산책 중 환경 재평가와 대체 경로.

실시간 강수 감지가 아니라 시간별 예보를 기준으로 판단한다. 날씨 자료는 서버에서 최대
WEATHER_CACHE_MINUTES 동안 캐시되므로 화면에서는 몇 분 간격으로만 다시 확인한다.
"""
import math
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Pet, User, WalkingCourse
from app.recommender.features import build_features
from app.recommender.safety import DEMO, FORECAST, assess_course, assessment_payload
from app.recommender.text import hour_label
from app.recommender.timeslots import evaluate_slot, is_rainy
from app.recommender.types import TimeWindow
from app.services.recommendation_service import load_state, to_course_data, to_profile, windows_of
from app.services.routing_service import Approach, Router, haversine_m, plan_approach
from app.services.weather_service import get_weather

ALL_DAY = TimeWindow(0, 24)
WALK_METERS_PER_MIN = 60.0
MAX_ALTERNATIVE_DISTANCE_M = 1500.0
MAX_ALTERNATIVES = 2
LOCATION_MISSING = "현재 위치를 알 수 없어 복귀 경로를 계산하지 못했어요. 위치 권한을 확인하거나 지도를 보며 출발점으로 돌아가 주세요."
DATA_LIMIT = "시간별 예보로 판단해요. 실시간 강수 감지가 아니니 하늘 상태도 함께 살펴 주세요."


def _approach_payload(approach: Approach) -> dict:
    return {
        "mode": approach.mode,
        "distance_m": approach.distance_m,
        "duration_min": approach.duration_min,
        "route": approach.route,
        "notice": approach.notice,
    }


def _alternatives(db, course, reference, now, forecast, features, state, weather_source) -> list[dict]:
    """지금 걷기 시작해도 비를 피할 수 있고 위험 조건이 없는 가까운 코스."""
    candidates = []
    for other in db.scalars(select(WalkingCourse).where(WalkingCourse.id != course.id, WalkingCourse.area == course.area)):
        data = to_course_data(other)
        if not data.pet_allowed:
            continue
        from_here = haversine_m(reference, (other.start_lat, other.start_lng))
        if from_here > MAX_ALTERNATIVE_DISTANCE_M:
            continue
        start = now + timedelta(minutes=round(from_here / WALK_METERS_PER_MIN))
        slot = evaluate_slot(start, other.duration_min, ALL_DAY, forecast, features, state, now)
        if slot is None or slot.unsafe_reason or slot.rain_overlap_min > 0:
            continue
        assessment = assess_course(data, slot, features, weather_source)
        if assessment.blocked_reasons:
            continue
        candidates.append(
            {
                "course_id": other.id,
                "name": other.name,
                "distance_km": other.distance_km,
                "duration_min": other.duration_min,
                "from_here_m": round(from_here),
                "safety_score": assessment.score,
                "safety_level": assessment.level,
                "reason": f"출발점까지 약 {round(from_here)}m, 비 예보를 피해 약 {other.duration_min}분 걸을 수 있어요.",
            }
        )
    candidates.sort(key=lambda item: (-item["safety_score"], item["from_here_m"]))
    return candidates[:MAX_ALTERNATIVES]


def evaluate_alternative(
    db: Session,
    pet: Pet,
    user: User,
    course: WalkingCourse,
    position: tuple[float, float] | None,
    progress_m: float,
    scenario: str,
    now: datetime,
    router: Router | None = None,
) -> dict:
    weather = get_weather(db, now, windows_of(user), scenario)
    forecast = {hour.time: hour for hour in weather.hours}
    features = build_features(to_profile(pet))
    state = load_state(db, pet)
    data = to_course_data(course)
    weather_source = DEMO if weather.is_mock else FORECAST

    total_m = course.distance_km * 1000
    remaining_m = max(0.0, total_m - max(0.0, progress_m))
    pace = total_m / course.duration_min
    remaining_min = max(1, math.ceil(remaining_m / pace))

    base = {
        "course_id": course.id,
        "remaining_m": round(remaining_m),
        "remaining_min": remaining_min,
        "checked_at": now,
        "cache_minutes": get_settings().weather_cache_minutes,
        "data_limit": DATA_LIMIT,
        "weather": {"source": weather.source, "scenario": weather.scenario, "is_mock": weather.is_mock, "notice": weather.notice},
    }

    slot = evaluate_slot(now, remaining_min, ALL_DAY, forecast, features, state, now)
    if slot is None:
        return {
            **base,
            "status": "unknown",
            "action": "continue",
            "reasons": ["지금 시간의 예보를 찾지 못했어요. 하늘 상태를 직접 확인해 주세요."],
            "assessment": None,
            "return_route": None,
            "location_notice": None,
            "alternatives": [],
        }

    assessment = assess_course(data, slot, features, weather_source)
    reasons: list[str] = []
    if slot.unsafe_reason:
        status = "return_now"
        reasons.append(f"지금은 {slot.unsafe_reason}가 있어요. 산책을 멈추고 돌아가는 편이 좋아요.")
    elif is_rainy(slot.weather):
        status = "shorten"
        reasons.append("지금 비가 내리거나 내릴 가능성이 높아요.")
    elif slot.rain_overlap_min > 0:
        status = "shorten"
        reasons.append(f"남은 약 {remaining_min}분 중 {slot.rain_overlap_min}분이 비 예보와 겹쳐요.")
    elif assessment.blocked_reasons:
        status = "shorten"
        reasons.extend(assessment.blocked_reasons)
    else:
        status = "continue"
        reasons.append(f"남은 약 {remaining_min}분 동안 큰 위험 조건은 예보되지 않았어요.")
        if slot.before_rain and slot.rain_onset:
            reasons.append(f"{hour_label(slot.rain_onset.hour)}부터 비 예보가 있으니 늦어지지 않게 다녀오세요.")

    return_route = None
    location_notice = None
    if position is None:
        location_notice = LOCATION_MISSING
    elif status != "continue":
        return_route = plan_approach(position, (course.start_lat, course.start_lng), router=router)

    if status == "continue":
        action = "continue"
    elif return_route is None:
        action = "no_location"
    elif return_route.mode == "too_far":
        action = "no_walking_route"
    elif return_route.distance_m < remaining_m:
        action = "return_to_start"
    else:
        # 순환 코스 후반이라면 되돌아가는 것보다 마저 걷는 편이 빠를 수 있다.
        action = "finish_course"

    reference = position or (course.start_lat, course.start_lng)
    alternatives = [] if status == "continue" else _alternatives(db, course, reference, now, forecast, features, state, weather_source)

    return {
        **base,
        "status": status,
        "action": action,
        "reasons": reasons,
        "assessment": assessment_payload(assessment),
        "return_route": _approach_payload(return_route) if return_route else None,
        "location_notice": location_notice,
        "alternatives": alternatives,
    }
