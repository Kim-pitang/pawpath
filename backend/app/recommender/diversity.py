"""비슷한 코스 판단: 경로가 얼마나 겹치는지.

경로는 단순화되어 지점 사이가 수십~수백 m라, 점끼리가 아니라 점과 선분 사이 거리로 잰다.
짧은 코스가 긴 코스에 통째로 들어가 있어도 같은 길로 보도록, 두 방향 중 큰 값을 쓴다.
"""
import math
from functools import lru_cache

Route = tuple[tuple[float, float], ...]

NEAR_M = 40.0
# 경로의 60% 이상이 다른 코스의 40m 안을 지나면 같은 길로 본다.
DUPLICATE_OVERLAP = 0.6
SAMPLE_STEP_M = 25.0
EARTH_M_PER_DEG = 111_320.0


def _project(route: Route, origin: tuple[float, float]) -> list[tuple[float, float]]:
    """위경도를 origin 기준 미터 단위 평면 좌표로 바꾼다. 두 경로에 같은 origin을 써야 비교할 수 있다."""
    lat0, lng0 = origin
    scale = math.cos(math.radians(lat0))
    return [((lng - lng0) * EARTH_M_PER_DEG * scale, (lat - lat0) * EARTH_M_PER_DEG) for lat, lng in route]


def _densify(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """긴 선분 위에 일정 간격으로 점을 더한다. 겹친 길이를 지점 개수가 아니라 거리로 세기 위해서다."""
    dense: list[tuple[float, float]] = []
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        length = math.hypot(x2 - x1, y2 - y1)
        steps = max(1, int(length // SAMPLE_STEP_M))
        dense.extend((x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps) for i in range(steps))
    if points:
        dense.append(points[-1])
    return dense


def _segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _covered_share(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
    samples = _densify(a)
    if not samples or len(b) < 2:
        return 0.0
    segments = list(zip(b, b[1:]))
    near = sum(1 for px, py in samples if any(_segment_distance(px, py, *s, *e) <= NEAR_M for s, e in segments))
    return near / len(samples)


@lru_cache(maxsize=4096)
def route_overlap(a: Route, b: Route) -> float:
    """0~1. 한쪽 경로가 다른 경로를 따라가는 비율 중 큰 값."""
    if len(a) < 2 or len(b) < 2:
        return 0.0
    pa, pb = _project(a, a[0]), _project(b, a[0])
    return round(max(_covered_share(pa, pb), _covered_share(pb, pa)), 3)
