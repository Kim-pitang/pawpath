"""생성한 경로 후보가 이 반려견과 이 시간에 얼마나 맞는지 평가한다.

길찾기로 만든 경로는 길이와 시간만 안다. 그래서 미리 수집해 둔 서비스 지역의 OpenStreetMap 자료(osm_area_service)로
후보마다 도로·조명·노면·나무·공원을 측정하고, 미리 수집한 시설(공원, 화장실, 음수대, 동물병원)을 센 뒤,
내 산책길을 추천 후보로 등록할 때와 같은 변환으로 추천 엔진 입력(CourseData)을 만들어 같은 엔진에 넣는다.
새 점수 체계를 따로 두지 않으므로 반려견 성향, 날씨, 일정, 지난 피드백 학습이 그대로 반영된다.

측정하지 못한 값(수집 범위 밖, 태그 없음)은 중립값으로 계산하되 '확인 불가'로 남기고 안전하다고 보지 않는다.
"""
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime

from app.recommender.config import ScoringConfig
from app.recommender.engine import recommend
from app.recommender.explain import hour_label
from app.recommender.safety import DEMO, FORECAST
from app.recommender.types import CourseData, PetProfile, PreferenceState, RecommendationResult, Schedule
from app.services import environment_service, osm_area_service
from app.services.user_course_service import WALK_KMH, course_attributes, nearby_facilities, route_km, simplify
from app.services.weather_service import WeatherResult

MARGIN_DEG = 0.0008  # 후보 한 개의 측정에 쓸 자료를 고를 때 경로 상자에 더하는 여유(약 90m)
FACILITY_LABELS = {"park": "공원", "toilets": "화장실", "drinking_water": "음수대", "veterinary": "동물병원"}


@dataclass
class CandidateFit:
    """후보 하나의 평가. excluded가 있으면 추천 엔진이 이 시간대에 권하지 않은 경로다."""

    score: float | None = None
    rank: int | None = None
    level: str | None = None
    summary: str = ""
    details: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)
    start: datetime | None = None
    start_label: str | None = None
    unknown: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)


@dataclass
class FitReport:
    fits: list[CandidateFit]  # 입력 후보와 같은 순서
    order: list[int]  # 추천 순서대로 후보 번호
    environment_measured: bool
    blocked_reasons: list[str] = field(default_factory=list)


def measure_candidates(routes: list[list[list[float]]]) -> list[dict | None]:
    """후보마다 주변 환경 측정값. 미리 수집한 자료가 덮지 않는 곳이면 모두 None(확인 불가)이다."""
    if not routes:
        return []
    area = osm_area_service.area_for([point for route in routes for point in route])
    if area is None:
        return [None] * len(routes)
    measured: list[dict | None] = []
    for route in routes:
        lats = [p[0] for p in route]
        lngs = [p[1] for p in route]
        box = (min(lats) - MARGIN_DEG, min(lngs) - MARGIN_DEG, max(lats) + MARGIN_DEG, max(lngs) + MARGIN_DEG)
        measured.append(
            environment_service.measure_environment(
                route, osm_area_service.near(area.ways, box), osm_area_service.near(area.trees, box), osm_area_service.near(area.parks, box), area.collected_on
            )
        )
    return measured


def build_course(index: int, route: list[list[float]], environment: dict | None) -> tuple[CourseData, list[dict]]:
    """후보 하나를 추천 엔진 입력으로. 번호는 음수로 두어 저장된 코스의 학습 기록과 섞이지 않게 한다."""
    simplified = simplify(route)
    distance_km = route_km(route)
    attributes, unknown = course_attributes(environment, recorded=False)
    facilities = nearby_facilities(simplified)
    course = CourseData(
        id=-(index + 1),
        name=f"후보 {index + 1}",
        distance_km=round(distance_km, 2),
        duration_min=max(10, round(distance_km / WALK_KMH * 60 / 5) * 5),
        has_park=attributes["has_park"],
        lighting=attributes["lighting"],
        is_paved=attributes["is_paved"],
        crowd_level=attributes["crowd_level"],
        pet_allowed=True,
        is_familiar=False,
        shade_level=attributes["shade_level"],
        difficulty=attributes["difficulty"],
        traffic_exposure=attributes["traffic_exposure"],
        scenery_tags=tuple(attributes["scenery_tags"]),
        facility_counts=dict(Counter(f["type"] for f in facilities)),
        environment=environment or {},
        unknown=frozenset(unknown),
    )
    return course, facilities


def _highlights(course: CourseData, facilities: list[dict]) -> list[str]:
    """화면에 그대로 보여 줄 측정 사실. 측정하지 못한 항목은 말하지 않는다."""
    lines: list[str] = []
    env = course.environment
    if "has_park" not in course.unknown and isinstance(env.get("park"), (int, float)) and env["park"] > 0:
        names = sorted({f["name"] for f in facilities if f["type"] == "park" and f["name"]})
        lines.append(f"공원을 지나는 길이 약 {env['park']:.0%}" + (f" ({', '.join(names[:2])})" if names else ""))
    road = env.get("road") or {}
    if "traffic_exposure" not in course.unknown:
        lines.append(f"큰 도로변 비율 약 {road.get('major', 0.0):.0%}")
    if "shade_level" not in course.unknown:
        lines.append(f"나무가 가까운 길 약 {course.shade_level:.0%}")
    counts = course.facility_counts
    found = [f"{FACILITY_LABELS[kind]} {counts[kind]}곳" for kind in ("toilets", "drinking_water", "veterinary") if counts.get(kind)]
    if found:
        lines.append("가까이 있는 시설: " + ", ".join(found))
    return lines


def fit_candidates(
    routes: list[list[list[float]]],
    pet: PetProfile,
    schedule: Schedule,
    state: PreferenceState,
    weather: WeatherResult,
    now: datetime,
    config: ScoringConfig,
    target_min: int,
) -> FitReport:
    """후보를 추천 엔진으로 평가한다. 평가 순서가 추천 순서다."""
    environments = measure_candidates(routes)
    built = [build_course(index, route, env) for index, (route, env) in enumerate(zip(routes, environments))]
    courses = [course for course, _ in built]
    # 사용자가 이번에 고른 시간이 이 산책의 희망 시간이다. 일정에 적어 둔 평소 희망 시간으로 비교하지 않는다.
    result: RecommendationResult = recommend(
        pet=pet,
        courses=courses,
        forecast_hours=weather.hours,
        schedule=replace(schedule, preferred_duration_min=target_min),
        state=state,
        now=now,
        config=config,
        weather_source=DEMO if weather.is_mock else FORECAST,
        top_n=len(courses),
    )
    fits = [CandidateFit(highlights=_highlights(course, facilities), unknown=sorted(course.unknown)) for course, facilities in built]
    by_id = {course.id: index for index, course in enumerate(courses)}
    order: list[int] = []
    for item in result.courses:
        index = by_id[item.course.id]
        fit = fits[index]
        fit.score = item.total_score
        fit.rank = item.rank
        fit.level = item.safety.level
        fit.summary = item.explanation.summary
        fit.details = list(item.explanation.details)
        fit.cautions = list(item.explanation.cautions) + list(item.explanation.other_cautions)
        fit.start = item.slot.start
        fit.start_label = hour_label(item.slot.start.hour)
        order.append(index)
    for item in result.excluded:
        fits[by_id[item.course.id]].excluded = list(item.reasons)
    # 권하지 않은 후보는 뒤에 두되 버리지 않는다. 길이 나쁘다는 뜻이 아니라 이 시간대 조건 때문일 수 있다.
    order += [index for index in range(len(courses)) if index not in order]
    return FitReport(fits=fits, order=order, environment_measured=all(env is not None for env in environments), blocked_reasons=list(result.blocked_reasons))
