"""코스 경로의 환경값을 OpenStreetMap 자료로 계산한다.

시드 코스를 만드는 scripts/enrich_courses.py와, 내 산책길을 추천 후보로 등록할 때 함께 쓴다.
경로를 10m 간격으로 나눠 가장 가까운 길의 태그를 읽어 도로 유형, 조명, 노면 비율과 나무, 공원 비율을 구한다.
태그가 없는 구간은 unknown으로 남겨 앱에서 '확인 불가'로 표시되게 한다.
"""
import math

SAMPLE_M = 10.0
WAY_MATCH_M = 15.0
TREE_MATCH_M = 15.0

PEDESTRIAN = {"footway", "path", "pedestrian", "steps", "cycleway", "track", "bridleway"}
LOCAL = {"residential", "living_street", "service", "unclassified", "road"}
MAJOR = {"tertiary", "tertiary_link", "secondary", "secondary_link", "primary", "primary_link", "trunk", "trunk_link", "motorway", "motorway_link"}
PAVED = {"paved", "asphalt", "concrete", "concrete:plates", "paving_stones", "sett", "metal", "wood", "tartan"}
UNPAVED = {"unpaved", "dirt", "earth", "ground", "grass", "gravel", "fine_gravel", "compacted", "mud", "sand", "pebblestone", "woodchips"}

def to_xy(lat: float, lng: float, origin_lat: float) -> tuple[float, float]:
    return lng * 111320 * math.cos(math.radians(origin_lat)), lat * 110540


def point_segment_m(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == dy == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def sample_route(route: list[list[float]]) -> list[tuple[float, float]]:
    origin = route[0][0]
    samples = []
    for (lat1, lng1), (lat2, lng2) in zip(route, route[1:]):
        ax, ay = to_xy(lat1, lng1, origin)
        bx, by = to_xy(lat2, lng2, origin)
        steps = max(1, round(math.hypot(bx - ax, by - ay) / SAMPLE_M))
        for step in range(steps):
            t = step / steps
            samples.append((lat1 + (lat2 - lat1) * t, lng1 + (lng2 - lng1) * t))
    return samples


def prepared_ways(elements: list[dict], origin: float) -> list[tuple[dict, list[tuple[float, float]]]]:
    ways = []
    for element in elements:
        geometry = element.get("geometry") or []
        if len(geometry) >= 2:
            ways.append((element.get("tags", {}), [to_xy(node["lat"], node["lon"], origin) for node in geometry]))
    return ways


def nearest_way(point, ways, limit: float) -> dict | None:
    best = None
    best_distance = limit
    for tags, points in ways:
        for a, b in zip(points, points[1:]):
            distance = point_segment_m(point, a, b)
            if distance <= best_distance:
                best, best_distance = tags, distance
    return best


def share(counter: dict[str, int], total: int) -> dict[str, float]:
    return {key: round(value / total, 3) for key, value in counter.items()}


def measure_roads(samples, ways, origin) -> dict:
    road = {"pedestrian": 0, "local": 0, "major": 0, "unknown": 0}
    lit = {"yes": 0, "no": 0, "unknown": 0}
    surface = {"paved": 0, "unpaved": 0, "unknown": 0}
    for lat, lng in samples:
        tags = nearest_way(to_xy(lat, lng, origin), ways, WAY_MATCH_M) or {}
        kind = tags.get("highway")
        road["pedestrian" if kind in PEDESTRIAN else "local" if kind in LOCAL else "major" if kind in MAJOR else "unknown"] += 1
        value = tags.get("lit")
        lit["yes" if value in ("yes", "24/7", "automatic") else "no" if value == "no" else "unknown"] += 1
        kind_surface = tags.get("surface")
        surface["paved" if kind_surface in PAVED else "unpaved" if kind_surface in UNPAVED else "unknown"] += 1
    total = len(samples)
    return {"road": share(road, total), "lit": share(lit, total), "surface": share(surface, total)}


def point_in_polygon(point, polygon) -> bool:
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def measure_trees(samples, elements, origin) -> float:
    nodes = []
    lines = []
    polygons = []
    for element in elements:
        if element["type"] == "node":
            nodes.append(to_xy(element["lat"], element["lon"], origin))
            continue
        points = [to_xy(node["lat"], node["lon"], origin) for node in element.get("geometry") or []]
        if len(points) < 2:
            continue
        lines.append(points)
        if points[0] == points[-1] and len(points) >= 4:
            polygons.append(points)

    near = 0
    for lat, lng in samples:
        point = to_xy(lat, lng, origin)
        close = any(math.hypot(point[0] - n[0], point[1] - n[1]) <= TREE_MATCH_M for n in nodes)
        close = close or any(point_in_polygon(point, polygon) for polygon in polygons)
        close = close or any(point_segment_m(point, a, b) <= TREE_MATCH_M for line in lines for a, b in zip(line, line[1:]))
        near += close
    return round(near / len(samples), 3)


def measure_parks(samples, elements, origin) -> float:
    polygons = []
    for element in elements:
        points = [to_xy(node["lat"], node["lon"], origin) for node in element.get("geometry") or []]
        if len(points) >= 4 and points[0] == points[-1]:
            polygons.append(points)
    inside = sum(1 for lat, lng in samples if any(point_in_polygon(to_xy(lat, lng, origin), polygon) for polygon in polygons))
    return round(inside / len(samples), 3)


def measure_environment(route: list[list[float]], ways: list[dict], trees: list[dict], parks: list[dict], collected_on: str) -> dict:
    origin = route[0][0]
    samples = sample_route(route)
    environment: dict = {"collected_on": collected_on, "sampled_points": len(samples)}
    environment.update(measure_roads(samples, prepared_ways(ways, origin), origin))
    environment["trees"] = measure_trees(samples, trees, origin)
    environment["park"] = measure_parks(samples, parks, origin)
    return environment


# 실행 중에 Overpass로 경로 주변 자료를 받는다. 테스트에서 가짜 서버로 바꿔 끼운다.
OVERPASS_MIRRORS = ("https://overpass-api.de/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter")
OVERPASS_TIMEOUT_SECONDS = 20.0
TRANSPORT = None
TREE_NATURAL = {"wood", "tree_row", "scrub", "tree"}
TREE_LANDUSE = {"forest", "meadow", "village_green"}
PARK_LEISURE = {"park", "garden", "dog_park"}


class EnvironmentUnavailable(Exception):
    """OSM 자료를 받지 못했다. 환경값은 '확인 불가'로 남긴다."""


def route_box(route: list[list[float]]) -> str:
    lats = [point[0] for point in route]
    lngs = [point[1] for point in route]
    return f"{min(lats) - 0.0006:.5f},{min(lngs) - 0.0007:.5f},{max(lats) + 0.0006:.5f},{max(lngs) + 0.0007:.5f}"


def fetch_osm(route: list[list[float]]) -> tuple[list[dict], list[dict], list[dict]]:
    """경로 주변의 길, 나무, 공원 기록을 한 번에 받아 나눈다."""
    import httpx  # 스크립트는 httpx 없이도 이 모듈의 계산 함수를 쓴다.

    box = route_box(route)
    query = (
        "[out:json][timeout:25];"
        f'way["highway"]({box});out tags geom;'
        f'(way["natural"~"^(wood|tree_row|scrub)$"]({box});way["landuse"~"^(forest|meadow|village_green)$"]({box});node["natural"="tree"]({box}););out tags geom;'
        f'way["leisure"~"^(park|garden|dog_park)$"]({box});out tags geom;'
    )
    last_error = "응답 없음"
    for url in OVERPASS_MIRRORS:
        try:
            with httpx.Client(timeout=OVERPASS_TIMEOUT_SECONDS, transport=TRANSPORT, headers={"User-Agent": "PawPath-hackathon/0.3"}) as client:
                response = client.post(url, data={"data": query})
            if response.status_code == 200:
                elements = response.json()["elements"]
                break
            last_error = f"HTTP {response.status_code}"
        except (httpx.HTTPError, ValueError, KeyError) as error:
            last_error = type(error).__name__
    else:
        raise EnvironmentUnavailable(last_error)

    ways, trees, parks = [], [], []
    for element in elements:
        tags = element.get("tags", {})
        if "highway" in tags and element.get("type") == "way":
            ways.append(element)
        if tags.get("natural") in TREE_NATURAL or tags.get("landuse") in TREE_LANDUSE:
            trees.append(element)
        if tags.get("leisure") in PARK_LEISURE and element.get("type") == "way":
            parks.append(element)
    return ways, trees, parks
