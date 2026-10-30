"""현재 위치에서 코스 출발점까지의 도보 경로.

코스 경로는 미리 구축해 두지만, 출발점까지의 길은 현재 위치에 따라 달라 실행 중에 계산한다.
위치는 경로 계산에만 쓰며 DB에 저장하거나 로그에 남기지 않는다.
"""
import logging
import math
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)
# httpx는 INFO 로그에 요청 주소를 남기는데, 이 주소에 사용자 좌표가 들어 있다.
logging.getLogger("httpx").setLevel(logging.WARNING)

WALK_METERS_PER_MIN = 60.0  # 반려동물과 걷는 속도 3.6km/h. 코스 소요 시간과 같은 기준이다.
ROUTING_FAILED_NOTICE = "길찾기 서버에 연결하지 못해 직선으로 표시했어요. 실제 길을 확인하며 이동해 주세요."
ROUTING_DISABLED_NOTICE = "길찾기를 사용하지 않아 직선으로 표시했어요. 실제 길을 확인하며 이동해 주세요."

LatLng = tuple[float, float]


class RoutingUnavailable(Exception):
    """길찾기 제공자에서 경로를 가져오지 못했다."""


@dataclass(frozen=True)
class RoutedPath:
    points: list[list[float]]
    distance_m: float


class Router(Protocol):
    def route(self, origin: LatLng, destination: LatLng) -> RoutedPath:
        """도보 경로를 돌려준다. 실패하면 RoutingUnavailable을 던진다."""
        ...


class OsrmFootRouter:
    def __init__(self, base_url: str, timeout_seconds: float, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.client = client

    def route(self, origin: LatLng, destination: LatLng) -> RoutedPath:
        coordinates = f"{origin[1]},{origin[0]};{destination[1]},{destination[0]}"
        url = f"{self.base_url}/route/v1/foot/{coordinates}"
        try:
            client = self.client or httpx.Client(timeout=self.timeout_seconds)
            response = client.get(url, params={"overview": "full", "geometries": "geojson"})
            response.raise_for_status()
            route = response.json()["routes"][0]
            points = [[lat, lng] for lng, lat in route["geometry"]["coordinates"]]
            return RoutedPath(points=points, distance_m=float(route["distance"]))
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            # 예외 메시지에는 좌표가 든 주소가 포함될 수 있어 종류만 전달한다.
            raise RoutingUnavailable(type(exc).__name__) from None


@dataclass(frozen=True)
class Approach:
    mode: str  # routed | straight | too_far
    distance_m: float
    duration_min: int
    route: list[list[float]]
    notice: str | None


def haversine_m(a: LatLng, b: LatLng) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def _minutes(distance_m: float) -> int:
    return max(1, round(distance_m / WALK_METERS_PER_MIN))


def _straight(origin: LatLng, destination: LatLng, distance_m: float, notice: str) -> Approach:
    return Approach(
        mode="straight",
        distance_m=round(distance_m, 1),
        duration_min=_minutes(distance_m),
        route=[list(origin), list(destination)],
        notice=notice,
    )


def build_router(settings: Settings) -> Router | None:
    if settings.routing_provider == "osrm":
        return OsrmFootRouter(settings.routing_base_url, settings.routing_timeout_seconds)
    return None


def plan_approach(
    origin: LatLng,
    destination: LatLng,
    router: Router | None = None,
    settings: Settings | None = None,
) -> Approach:
    """출발점까지의 안내 경로를 만든다. 너무 멀면 도보 안내를 하지 않고, 실패하면 직선으로 대체한다."""
    settings = settings or get_settings()
    straight_m = haversine_m(origin, destination)

    if straight_m > settings.routing_max_distance_km * 1000:
        return Approach(mode="too_far", distance_m=round(straight_m, 1), duration_min=_minutes(straight_m), route=[], notice=None)

    router = router or build_router(settings)
    if router is None:
        return _straight(origin, destination, straight_m, ROUTING_DISABLED_NOTICE)

    try:
        path = router.route(origin, destination)
    except RoutingUnavailable as exc:
        logger.warning("길찾기 실패, 직선으로 대체합니다: %s", exc)
        return _straight(origin, destination, straight_m, ROUTING_FAILED_NOTICE)

    return Approach(
        mode="routed",
        distance_m=round(path.distance_m, 1),
        duration_min=_minutes(path.distance_m),
        route=path.points,
        notice=None,
    )
