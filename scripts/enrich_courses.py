#!/usr/bin/env python3
"""코스별 환경 실측값과 주변 시설을 OpenStreetMap 자료로 계산한다.

경로 좌표는 바꾸지 않는다. 경로를 10m 간격으로 나눠 가장 가까운 길의 태그를 읽어
도로 유형, 조명, 노면 비율과 나무 기록 근접 비율을 구하고 courses.json의 environment에 넣는다.
태그가 없는 구간은 unknown으로 남겨, 앱에서 '확인 불가'로 표시되게 한다.

입력 폴더에는 Overpass 응답을 다음 이름으로 저장해 둔다.
  ways_<코스코드>.json   way["highway"](코스 범위);out tags geom;
  trees_<코스코드>.json  나무, 숲 기록
  parks_<코스코드>.json  공원 기록
  place_<종류>.json      주변 시설

사용법: python3 scripts/enrich_courses.py <입력 폴더>
"""
import json
import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COURSES_PATH = ROOT / "backend" / "app" / "data" / "courses.json"
PLACES_PATH = ROOT / "backend" / "app" / "data" / "places.json"

SAMPLE_M = 10.0
WAY_MATCH_M = 15.0
TREE_MATCH_M = 15.0

PEDESTRIAN = {"footway", "path", "pedestrian", "steps", "cycleway", "track", "bridleway"}
LOCAL = {"residential", "living_street", "service", "unclassified", "road"}
MAJOR = {"tertiary", "tertiary_link", "secondary", "secondary_link", "primary", "primary_link", "trunk", "trunk_link", "motorway", "motorway_link"}
PAVED = {"paved", "asphalt", "concrete", "concrete:plates", "paving_stones", "sett", "metal", "wood", "tartan"}
UNPAVED = {"unpaved", "dirt", "earth", "ground", "grass", "gravel", "fine_gravel", "compacted", "mud", "sand", "pebblestone", "woodchips"}

PLACE_FILES = {
    "park": "place_park",
    "dog_park": "place_dog_park",
    "veterinary": "place_veterinary",
    "drinking_water": "place_drinking_water",
    "toilets": "place_toilets",
    "convenience": "place_convenience",
    "pet_shop": "place_pet_shop",
}
PET_FRIENDLY_FILES = ("place_dog_tag", "place_pets_tag")


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


def load_elements(folder: Path, name: str) -> list[dict] | None:
    path = folder / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))["elements"] if path.exists() else None


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


def build_environment(course: dict, folder: Path, today: str) -> tuple[dict, list[str]]:
    origin = course["route"][0][0]
    samples = sample_route(course["route"])
    environment: dict = {"collected_on": today, "sampled_points": len(samples)}
    missing = []

    ways = load_elements(folder, f"ways_{course['code']}")
    if ways is None:
        missing.append("도로·조명·노면")
    else:
        environment.update(measure_roads(samples, prepared_ways(ways, origin), origin))

    trees = load_elements(folder, f"trees_{course['code']}")
    if trees is None:
        environment["trees"] = None
        missing.append("나무")
    else:
        environment["trees"] = measure_trees(samples, trees, origin)

    parks = load_elements(folder, f"parks_{course['code']}")
    if parks is None:
        environment["park"] = None
        missing.append("공원 면적")
    else:
        environment["park"] = measure_parks(samples, parks, origin)
    return environment, missing


def place_rows(elements: list[dict], kind: str) -> list[dict]:
    rows = []
    for element in elements:
        center = element.get("center") or {"lat": element.get("lat"), "lon": element.get("lon")}
        if center.get("lat") is None:
            continue
        tags = element.get("tags", {})
        rows.append({"type": kind, "name": tags.get("name", ""), "lat": center["lat"], "lng": center["lon"]})
    return rows


def build_places(folder: Path, today: str) -> dict:
    places = []
    unavailable = []
    for kind, name in PLACE_FILES.items():
        elements = load_elements(folder, name)
        if elements is None:
            unavailable.append(kind)
        else:
            places.extend(place_rows(elements, kind))

    friendly_loaded = False
    for name in PET_FRIENDLY_FILES:
        elements = load_elements(folder, name)
        if elements is not None:
            friendly_loaded = True
            places.extend(place_rows(elements, "pet_friendly"))
    if not friendly_loaded:
        unavailable.append("pet_friendly")
    return {"collected_on": today, "source": "OpenStreetMap", "unavailable_types": unavailable, "places": places}


def main() -> None:
    folder = Path(sys.argv[1])
    today = date.today().isoformat()
    courses = json.loads(COURSES_PATH.read_text(encoding="utf-8"))
    for course in courses:
        # 경로가 공원을 지나지 않으므로 '공원 포함'이 아니다. 공원 이름은 주변 표시에 쓴다.
        if course["code"] == "mangwon-forest":
            course["has_park"] = False
            course["scenery_tags"] = [tag for tag in course["scenery_tags"] if tag != "park"]
    for course in courses:
        environment, missing = build_environment(course, folder, today)
        course["environment"] = environment
        # 도로 기록이 충분하면 차량 노출은 추정값 대신 실측으로 정한다.
        road_share = environment.get("road")
        if road_share and road_share["unknown"] <= 0.3:
            course["traffic_exposure"] = "high" if road_share["major"] >= 0.3 else "medium" if road_share["major"] >= 0.1 else "low"
            course["data_sources"]["team_estimates"] = [item for item in course["data_sources"]["team_estimates"] if item != "traffic_exposure"]
        course["data_sources"]["environment"] = f"OpenStreetMap Overpass ({today}), 경로 10m 간격 측정"
        course["data_sources"]["environment_unavailable"] = missing
        road = environment.get("road", {})
        lit = environment.get("lit", {})
        print(
            f"{course['code']:<22} 보행 {road.get('pedestrian', 0):.0%} 생활 {road.get('local', 0):.0%} 큰길 {road.get('major', 0):.0%} 미상 {road.get('unknown', 0):.0%}"
            f" | 조명 기록 {lit.get('yes', 0) + lit.get('no', 0):.0%} | 나무 {environment.get('trees')} | 공원 {environment.get('park')} | 누락 {missing or '없음'}"
        )
    COURSES_PATH.write_text(json.dumps(courses, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    places = build_places(folder, today)
    PLACES_PATH.write_text(json.dumps(places, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    counts: dict[str, int] = {}
    for place in places["places"]:
        counts[place["type"]] = counts.get(place["type"], 0) + 1
    print("시설:", counts, "/ 못 받은 종류:", places["unavailable_types"] or "없음")


if __name__ == "__main__":
    main()
