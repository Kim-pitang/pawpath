"""내 산책길을 추천 후보 코스로 등록한다.

경로와 거리는 산책길 그대로 쓰고, 도로, 조명, 노면, 나무, 공원은 OSM에서 시드 코스와 같은 방법으로 측정한다.
공개 Overpass 서버는 응답에 30초 넘게 걸리기도 해서, 등록은 바로 끝내고 측정은 응답을 보낸 뒤에 한다.
측정 전이나 측정에 실패한 값, 혼잡도와 경사처럼 측정할 수 없는 값은 중립값으로 계산하되
'확인 불가'로 표시하고 안전하다고 보지 않는다.
"""
import math
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import now_local
from app.config import SERVICE_AREAS, Settings
from app.database import SessionLocal
from app.models import SavedWalk, User, WalkingCourse
from app.services import environment_service
from app.services.places_service import load_places
from app.services.saved_walk_service import haversine_m

MAX_COURSE_KM = 10.0
# 일시정지나 GPX 구간 사이가 이보다 떨어져 있으면 한 코스로 이을 수 없다.
MAX_GAP_M = 100.0
# 이 거리 안에 출발점이 있어야 그 지역의 날씨로 추천할 수 있다.
AREA_RADIUS_M = 5000.0
SIMPLIFY_M = 4.0
WALK_KMH = 3.6
FACILITY_RADIUS_M = {"veterinary": 200}
DEFAULT_FACILITY_RADIUS_M = 60
FACILITY_TYPES = ("toilets", "drinking_water", "veterinary", "park")
# 경로가 공원을 조금이라도 지나면 공원 코스로 본다. 시드 코스 16개의 팀 판정과 측정값을 비교해 정했다
# (측정 비율이 0보다 큰 코스는 모두 팀도 공원 코스로 판정, 가장 낮은 값이 1.6%).
PARK_SHARE = 0.01
# 측정 중에 서버가 다시 시작되면 결과가 오지 않으므로, 이 시간이 지나면 실패로 본다.
MEASURE_TIMEOUT = timedelta(minutes=5)
PET_RULE = "리드줄과 배변봉투를 챙기고, 출입 제한 구역은 현장 안내를 따라 주세요."


class CourseError(ValueError):
    """화면에 그대로 보여 줄 수 있는 등록 실패 이유."""


def joined_route(walk: SavedWalk) -> list[list[float]]:
    """구간을 이어 하나의 경로로 만든다. 구간 사이가 멀면 거부한다."""
    route: list[list[float]] = []
    segment = None
    for point in walk.points:
        here = [point.latitude, point.longitude]
        if route and point.segment != segment:
            gap = haversine_m(*route[-1], *here)
            if gap > MAX_GAP_M:
                raise CourseError(f"끊긴 구간 사이가 {gap:.0f}m 떨어져 있어 하나의 코스로 이을 수 없어요.")
        if not route or here != route[-1]:
            route.append(here)
        segment = point.segment
    if len(route) < 2:
        raise CourseError("코스로 만들 지점이 부족해요.")
    return route


def simplify(points: list[list[float]], tolerance_m: float = SIMPLIFY_M) -> list[list[float]]:
    """더글러스-포이커 단순화. 지점이 많아도 재귀 깊이가 늘지 않게 스택으로 처리한다."""
    if len(points) < 3:
        return points
    origin = points[0][0]
    meters = [environment_service.to_xy(lat, lng, origin) for lat, lng in points]
    keep = {0, len(points) - 1}
    # 왕복 경로는 시작점과 끝점이 같아 기준선이 없으므로 가장 먼 점에서 먼저 나눈다.
    middle = max(range(len(points)), key=lambda i: math.hypot(meters[i][0] - meters[0][0], meters[i][1] - meters[0][1]))
    stack = [(0, middle), (middle, len(points) - 1)] if 0 < middle < len(points) - 1 else [(0, len(points) - 1)]
    keep.add(middle)
    while stack:
        first, last = stack.pop()
        worst, worst_index = 0.0, -1
        for index in range(first + 1, last):
            distance = environment_service.point_segment_m(meters[index], meters[first], meters[last])
            if distance > worst:
                worst, worst_index = distance, index
        if worst > tolerance_m:
            keep.add(worst_index)
            stack += [(first, worst_index), (worst_index, last)]
    return [points[index] for index in sorted(keep)]


def route_km(route: list[list[float]]) -> float:
    return sum(haversine_m(*a, *b) for a, b in zip(route, route[1:])) / 1000


def area_label(route: list[list[float]]) -> str:
    start = route[0]
    distances = {area.label: haversine_m(start[0], start[1], area.latitude, area.longitude) for area in SERVICE_AREAS.values()}
    label, distance = min(distances.items(), key=lambda item: item[1])
    if distance > AREA_RADIUS_M:
        names = ", ".join(area.label.replace("서울 ", "").replace(" 일대", "") for area in SERVICE_AREAS.values())
        raise CourseError(f"추천은 서비스 지역({names}) 근처만 해요. 이 산책길의 출발점은 가장 가까운 지역에서 {distance / 1000:.1f}km 떨어져 있어요.")
    return label


def nearby_facilities(route: list[list[float]]) -> list[dict]:
    """미리 수집한 OSM 시설 중 경로 가까이 있는 것. 시드 코스와 같은 거리 기준을 쓴다."""
    origin = route[0][0]
    meters = [environment_service.to_xy(lat, lng, origin) for lat, lng in route]
    found = []
    for place in load_places()["places"]:
        if place["type"] not in FACILITY_TYPES:
            continue
        point = environment_service.to_xy(place["lat"], place["lng"], origin)
        limit = FACILITY_RADIUS_M.get(place["type"], DEFAULT_FACILITY_RADIUS_M)
        if min(environment_service.point_segment_m(point, a, b) for a, b in zip(meters, meters[1:])) <= limit:
            found.append({"type": place["type"], "lat": place["lat"], "lng": place["lng"], "name": place.get("name", "")})
    return found


def course_attributes(environment: dict | None, recorded: bool) -> tuple[dict, list[str]]:
    """측정값으로 엔진 입력을 정하고, 알 수 없는 속성 이름을 함께 돌려준다."""
    env = environment or {}
    unknown = ["crowd_level", "difficulty"]
    road = env.get("road") or {}
    if road and road.get("unknown", 1.0) <= 0.3:
        major = road.get("major", 0.0)
        traffic = "high" if major >= 0.3 else "medium" if major >= 0.1 else "low"
    else:
        traffic = "medium"
        unknown.append("traffic_exposure")

    lit = env.get("lit") or {}
    lit_known = lit.get("yes", 0.0) + lit.get("no", 0.0)
    if lit_known >= 0.5:
        lit_share = lit.get("yes", 0.0) / lit_known
        lighting = "good" if lit_share >= 0.7 else "partial" if lit_share >= 0.3 else "poor"
    else:
        lighting = "unknown"

    surface = env.get("surface") or {}
    surface_known = surface.get("paved", 0.0) + surface.get("unpaved", 0.0)
    if surface_known >= 0.5:
        unpaved = surface.get("unpaved", 0.0) / surface_known
        is_paved = unpaved < 0.3
        surface_note = f"OSM 기록 기준 포장 {1 - unpaved:.0%}"
    else:
        is_paved = True
        surface_note = "확인 불가"
        unknown.append("is_paved")

    trees = env.get("trees")
    if isinstance(trees, (int, float)) and trees > 0:
        shade_level = round(min(0.9, max(0.1, trees)), 2)
    else:
        shade_level = 0.5
        unknown.append("shade_level")

    park = env.get("park")
    if isinstance(park, (int, float)):
        has_park = park >= PARK_SHARE
    else:
        has_park = False
        unknown.append("has_park")

    tags = []
    if has_park:
        tags.append("park")
    if isinstance(trees, (int, float)) and trees >= 0.4:
        tags.append("forest")
    if road.get("local", 0.0) >= 0.5:
        tags.append("residential")
    return (
        {
            "has_park": has_park,
            "lighting": lighting,
            "is_paved": is_paved,
            "surface_note": surface_note,
            "crowd_level": "medium",
            "is_familiar": recorded,
            "shade_level": shade_level,
            "difficulty": "easy",
            "traffic_exposure": traffic,
            "scenery_tags": tags,
        },
        sorted(unknown),
    )


def register(db: Session, user: User, walk: SavedWalk, settings: Settings, now: datetime) -> tuple[WalkingCourse, str | None]:
    """산책길을 추천 후보로 등록한다. 이미 등록했으면 갱신하고 켠다.

    주변 환경 측정이 필요하면 측정 표를 함께 돌려준다. 호출한 쪽이 응답 뒤에 measure()를 부른다.
    """
    route = joined_route(walk)
    distance_km = route_km(route)
    if distance_km > MAX_COURSE_KM:
        raise CourseError(f"추천 코스는 {MAX_COURSE_KM:.0f}km까지 만들 수 있어요. 이 산책길은 {distance_km:.1f}km예요.")
    if distance_km < 0.1:
        raise CourseError("100m보다 짧은 산책길은 코스로 만들 수 없어요.")
    area = area_label(route)
    simplified = simplify(route)

    measuring = settings.environment_provider == "overpass"
    token = secrets.token_hex(8) if measuring else None
    recorded = walk.source_type == "recorded"
    attributes, unknown = course_attributes(None, recorded)
    facilities = nearby_facilities(simplified)
    places = load_places()
    values = {
        "name": walk.title[:80],
        "description": "직접 기록한 내 산책길이에요." if recorded else "GPX로 가져온 내 산책길이에요.",
        "area": area,
        "start_lat": simplified[0][0],
        "start_lng": simplified[0][1],
        "distance_km": round(distance_km, 2),
        "duration_min": max(10, round(distance_km / WALK_KMH * 60 / 5) * 5),
        "route": simplified,
        "park_names": sorted({f["name"] for f in facilities if f["type"] == "park" and f["name"]}),
        "pet_allowed": True,
        "pet_rule_note": PET_RULE,
        "facilities": facilities,
        "environment": None,
        "data_sources": {
            "route": "직접 기록한 GPS 경로" if recorded else "가져온 GPX 경로",
            "source_type": walk.source_type,
            "facilities": f"OpenStreetMap ({places.get('collected_on')})",
            "environment": None,
            "environment_status": "pending" if measuring else "off",
            "environment_unavailable": None,
            "measurement": token,
            "measurement_started": now.isoformat() if measuring else None,
            "team_estimates": [],
            "unknown": unknown,
        },
        "owner_user_id": user.id,
        "saved_walk_id": walk.id,
        "is_active": True,
        **attributes,
    }
    course = walk.course or db.scalar(select(WalkingCourse).where(WalkingCourse.code == f"walk-{walk.id}"))
    if course is None:
        course = WalkingCourse(code=f"walk-{walk.id}", **values)
        db.add(course)
    else:
        for key, value in values.items():
            setattr(course, key, value)
    db.commit()
    db.refresh(walk)
    return course, token


def measure(course_id: int, token: str) -> None:
    """응답을 보낸 뒤 주변 환경을 측정해 코스를 갱신한다. 그사이 다시 등록했으면 오래된 결과는 버린다."""
    with SessionLocal() as db:
        course = db.get(WalkingCourse, course_id)
        if course is None:
            return
        route = course.route
    today = now_local().date().isoformat()
    try:
        ways, trees, parks = environment_service.fetch_osm(route)
        environment = environment_service.measure_environment(route, ways, trees, parks, today)
        failure = None
    except environment_service.EnvironmentUnavailable as error:
        environment, failure = None, f"OSM 응답 실패({error})"

    with SessionLocal() as db:
        course = db.get(WalkingCourse, course_id)
        sources = dict(course.data_sources or {}) if course else {}
        if course is None or sources.get("measurement") != token:
            return
        attributes, unknown = course_attributes(environment, sources.get("source_type") == "recorded")
        for key, value in attributes.items():
            setattr(course, key, value)
        course.environment = environment
        sources.update(
            unknown=unknown,
            environment=f"OpenStreetMap Overpass ({today}), 경로 10m 간격 측정" if environment else None,
            environment_status="done" if environment else "failed",
            environment_unavailable=failure,
        )
        course.data_sources = sources
        db.commit()


def measurement_status(course: WalkingCourse, now: datetime) -> str:
    """pending, done, failed, off. 너무 오래 끝나지 않은 측정은 실패로 본다."""
    sources = course.data_sources or {}
    status = sources.get("environment_status") or ("done" if course.environment else "off")
    started = sources.get("measurement_started")
    if status == "pending" and started and now - datetime.fromisoformat(started) > MEASURE_TIMEOUT:
        return "failed"
    return status


def unregister(db: Session, walk: SavedWalk) -> None:
    """추천 후보에서 뺀다. 이 코스로 남긴 산책 기록이 있을 수 있어 지우지 않고 끈다."""
    if walk.course is not None:
        walk.course.is_active = False
        db.commit()
        db.refresh(walk)


def detach(db: Session, walk: SavedWalk) -> None:
    """산책길을 지우기 전에 코스를 끄고 연결을 끊는다."""
    course = walk.course
    if course is not None:
        course.is_active = False
        course.saved_walk_id = None
        db.flush()
