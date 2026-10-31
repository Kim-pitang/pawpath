#!/usr/bin/env python3
"""망원동 일대 산책 코스 시드 데이터를 만든다.

경유지는 팀이 정하고, 실제 경로와 거리는 OSRM 도보 경로로, 경로 주변 시설은
OpenStreetMap(Overpass)에서 가져온다. 결과는 backend/app/data/courses.json에 저장하므로
앱은 실행 중 이 외부 서비스에 의존하지 않는다.

OSM에 없는 혼잡도, 그늘, 조명, 차량 노출은 팀 추정값이며 data_sources에 그렇게 기록한다.

사용법: python3 scripts/build_courses.py [--cache-dir DIR]
"""
import argparse
import json
import math
import subprocess
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "backend" / "app" / "data" / "courses.json"

OVERPASS_MIRRORS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]
OSRM_FOOT = "https://routing.openstreetmap.de/routed-foot/route/v1/foot"
BBOX = "37.545,126.893,37.572,126.930"
FACILITY_QUERIES = {
    "toilets": f'nwr["amenity"="toilets"]({BBOX});out tags center;',
    "veterinary": f'nwr["amenity"="veterinary"]({BBOX});out tags center;',
    "drinking_water": f'nwr["amenity"="drinking_water"]({BBOX});out tags center;',
    "bench": f'nwr["amenity"="bench"]({BBOX});out tags center;',
    "waste_basket": f'nwr["amenity"="waste_basket"]({BBOX});out tags center;',
    "police": f'nwr["amenity"="police"]({BBOX});out tags center;',
    "surveillance": f'node["man_made"="surveillance"]({BBOX});out;',
    "park": f'nwr["leisure"="park"]({BBOX});out tags center;',
}
# 파일 이름 하위 호환: 조사 단계에서 받아 둔 캐시도 그대로 쓴다.
CACHE_ALIASES = {"veterinary": "vets", "drinking_water": "water", "bench": "benches", "waste_basket": "waste", "surveillance": "cctv", "park": "parks"}
FACILITY_RADIUS_M = {"veterinary": 200}
DEFAULT_RADIUS_M = 60
WALK_KMH = 3.6
PET_RULE = "리드줄과 배변봉투를 챙기고, 출입 제한 구역은 현장 안내를 따라 주세요."

COURSES = [
    {
        "code": "mangwon-greenway",
        "name": "망원초록길 공원 코스",
        "description": "망원동 주택가에서 망원정마당과 망원초록길을 잇는 짧은 일상 코스예요.",
        "waypoints": [(37.5545, 126.9065), (37.55111, 126.90341), (37.55114, 126.90227), (37.5530, 126.9025), (37.5545, 126.9065)],
        "has_park": True, "park_names": ["망원정마당", "망원초록길"],
        "lighting": "partial", "is_paved": True, "surface_note": "포장 보행로", "crowd_level": "low",
        "is_familiar": True, "shade_level": 0.5, "difficulty": "easy", "traffic_exposure": "low",
        "scenery_tags": ["park", "residential"],
    },
    {
        "code": "mangwon-station-park",
        "name": "망원역 남쪽 공원 산책",
        "description": "망원역에서 동네 골목을 지나 작은 공원까지 다녀오는 코스예요.",
        "waypoints": [(37.5560, 126.9105), (37.55047, 126.90852), (37.5527, 126.9125), (37.5560, 126.9105)],
        "has_park": True, "park_names": ["앙화공원"],
        "lighting": "good", "is_paved": True, "surface_note": "포장 골목길", "crowd_level": "medium",
        "is_familiar": True, "shade_level": 0.3, "difficulty": "easy", "traffic_exposure": "medium",
        "scenery_tags": ["park", "residential"],
    },
    {
        "code": "mangwon-forest",
        "name": "망원1동 동네숲 앞 골목길",
        "description": "주택가 골목을 지나 망원1동 동네숲 앞까지 다녀오는 한적한 코스예요.",
        "waypoints": [(37.5552, 126.9048), (37.55306, 126.90039), (37.5545, 126.9018), (37.5552, 126.9048)],
        "has_park": False, "park_names": ["망원1동 동네숲"],
        "lighting": "partial", "is_paved": True, "surface_note": "포장 골목길", "crowd_level": "low",
        "is_familiar": True, "shade_level": 0.4, "difficulty": "easy", "traffic_exposure": "low",
        "scenery_tags": ["residential"],
    },
    {
        "code": "mangwon-hangang",
        "name": "망원한강공원 강변길",
        "description": "망원초록길을 지나 한강변 산책로를 왕복하는 시원하게 트인 코스예요.",
        "waypoints": [(37.5530, 126.9045), (37.55114, 126.90227), (37.5478, 126.9050), (37.55114, 126.90227), (37.5530, 126.9045)],
        "has_park": True, "park_names": ["망원한강공원", "망원초록길"],
        "lighting": "good", "is_paved": True, "surface_note": "포장 산책로", "crowd_level": "high",
        "is_familiar": False, "shade_level": 0.1, "difficulty": "easy", "traffic_exposure": "low",
        "scenery_tags": ["river", "open", "park"],
    },
    {
        "code": "seoulham-riverside",
        "name": "서울함공원 강변 왕복",
        "description": "망원한강공원에서 서울함공원까지 한강 자전거길 옆을 따라 왕복하는 코스예요.",
        "waypoints": [(37.5490, 126.9035), (37.55114, 126.9000), (37.5535, 126.8972), (37.5548, 126.8950), (37.5535, 126.8972), (37.55114, 126.9000), (37.5490, 126.9035)],
        "has_park": True, "park_names": ["망원한강공원", "서울함공원"],
        "lighting": "partial", "is_paved": True, "surface_note": "포장 산책로", "crowd_level": "medium",
        "is_familiar": False, "shade_level": 0.2, "difficulty": "easy", "traffic_exposure": "low",
        "scenery_tags": ["river", "open", "park"],
    },
    {
        "code": "hangang-long",
        "name": "한강 강변 종주 코스",
        "description": "양화대교 쪽에서 서울함공원까지 한강변을 길게 왕복하는, 활동량 많은 아이를 위한 코스예요.",
        "waypoints": [(37.5447, 126.9085), (37.5490, 126.9035), (37.5535, 126.8972), (37.5548, 126.8950), (37.5535, 126.8972), (37.5490, 126.9035), (37.5447, 126.9085)],
        "has_park": True, "park_names": ["망원한강공원", "서울함공원"],
        "lighting": "partial", "is_paved": True, "surface_note": "포장 산책로", "crowd_level": "medium",
        "is_familiar": False, "shade_level": 0.1, "difficulty": "easy", "traffic_exposure": "low",
        "scenery_tags": ["river", "open", "park"],
    },
    {
        "code": "gyeongui-yeonnam",
        "name": "경의선숲길 연남동 구간",
        "description": "홍대입구역에서 연남동까지 이어지는 숲길 공원 코스예요. 볼거리가 많고 사람도 많아요.",
        "waypoints": [(37.5577, 126.9250), (37.56277, 126.92193), (37.5660, 126.9190), (37.5577, 126.9250)],
        "has_park": True, "park_names": ["경의선숲길공원"],
        "lighting": "good", "is_paved": True, "surface_note": "포장 산책로와 잔디", "crowd_level": "high",
        "is_familiar": False, "shade_level": 0.5, "difficulty": "easy", "traffic_exposure": "low",
        "scenery_tags": ["park", "urban", "forest"],
    },
    {
        "code": "hongjecheon",
        "name": "홍제천 산책로",
        "description": "홍제천서자전거길을 따라 하천변을 왕복하는 코스예요. 내부순환로 고가 아래를 지나요.",
        "waypoints": [(37.5663, 126.9134), (37.5650, 126.9075), (37.5635, 126.9019), (37.5650, 126.9075), (37.5663, 126.9134)],
        "has_park": False, "park_names": [],
        "lighting": "partial", "is_paved": True, "surface_note": "포장 하천 자전거길 옆", "crowd_level": "medium",
        "is_familiar": False, "shade_level": 0.4, "difficulty": "easy", "traffic_exposure": "low",
        "scenery_tags": ["stream", "open"],
    },
    {
        "code": "seongmisan",
        "name": "성미산 숲길",
        "description": "성미산로 골목에서 동네 뒷산 숲길로 들어가는 코스예요. 오르막이 있고 흙길이 있어요.",
        "waypoints": [(37.5630, 126.9095), (37.5622, 126.9110), (37.5610, 126.9120), (37.5603, 126.9105), (37.5615, 126.9095), (37.5630, 126.9095)],
        "has_park": True, "park_names": [],
        "lighting": "poor", "is_paved": False, "surface_note": "골목길과 흙길, 오르막 구간 있음", "crowd_level": "low",
        "is_familiar": False, "shade_level": 0.8, "difficulty": "moderate", "traffic_exposure": "low",
        "scenery_tags": ["forest", "hill"],
    },
    {
        "code": "peace-park",
        "name": "평화의공원 순환",
        "description": "월드컵공원의 평화의공원 안쪽을 도는 코스예요. 평탄하고 길이 넓어요.",
        "waypoints": [(37.5615, 126.8965), (37.5625, 126.8925), (37.5640, 126.8905), (37.5650, 126.8945), (37.5615, 126.8965)],
        "has_park": True, "park_names": ["평화의공원"],
        "lighting": "good", "is_paved": True, "surface_note": "포장 산책로", "crowd_level": "medium",
        "is_familiar": False, "shade_level": 0.4, "difficulty": "easy", "traffic_exposure": "low",
        "scenery_tags": ["park", "open"],
    },
]


def curl_json(args: list[str], timeout: int) -> dict:
    command = ["curl", "-s", "-f", "-m", str(timeout), "-A", "PawPath-hackathon/0.1", *args]
    return json.loads(subprocess.run(command, capture_output=True, check=True).stdout)


def fetch_facilities(cache_dir: Path) -> tuple[dict[str, list[dict]], list[str]]:
    """시설 종류별 좌표를 가져온다. 끝내 못 받은 종류는 목록으로 돌려줘 출처에 기록한다."""
    results: dict[str, list[dict]] = {}
    missing: list[str] = []
    for kind, body in FACILITY_QUERIES.items():
        cached = cache_dir / f"osm_{CACHE_ALIASES.get(kind, kind)}.json"
        data = json.loads(cached.read_text()) if cached.exists() else None
        for attempt in range(2 if data is None else 0):
            mirror = OVERPASS_MIRRORS[attempt % len(OVERPASS_MIRRORS)]
            try:
                data = curl_json(["-X", "POST", mirror, "--data-urlencode", f"data=[out:json][timeout:15];{body}"], 25)
                cached.write_text(json.dumps(data, ensure_ascii=False))
                break
            except (subprocess.CalledProcessError, json.JSONDecodeError):
                time.sleep(2)
        if data is None:
            missing.append(kind)
            continue
        points = []
        for element in data["elements"]:
            center = element.get("center") or {"lat": element.get("lat"), "lon": element.get("lon")}
            if center.get("lat") is not None:
                points.append({"lat": center["lat"], "lng": center["lon"], "name": element.get("tags", {}).get("name", "")})
        results[kind] = points
    return results, missing


def route_for(waypoints: list[tuple[float, float]]) -> dict:
    coordinates = ";".join(f"{lng},{lat}" for lat, lng in waypoints)
    url = f"{OSRM_FOOT}/{coordinates}?overview=full&geometries=geojson"
    for attempt in range(4):
        try:
            return curl_json([url], 25)["routes"][0]
        except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError):
            if attempt == 3:
                raise
            time.sleep(3)
    raise RuntimeError("unreachable")


def to_meters(lat: float, lng: float, origin_lat: float) -> tuple[float, float]:
    return lng * 111320 * math.cos(math.radians(origin_lat)), lat * 110540


def point_segment_distance(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == dy == 0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def distance_to_route(lat: float, lng: float, route: list[list[float]]) -> float:
    origin = route[0][0]
    point = to_meters(lat, lng, origin)
    meters = [to_meters(a, b, origin) for a, b in route]
    return min(point_segment_distance(point, meters[i], meters[i + 1]) for i in range(len(meters) - 1))


def simplify(points: list[list[float]], tolerance_m: float = 4.0) -> list[list[float]]:
    """더글러스-포이커 단순화. 왕복 경로의 저장 크기를 줄인다."""
    if len(points) < 3:
        return points
    origin = points[0][0]
    meters = [to_meters(a, b, origin) for a, b in points]

    def walk(first: int, last: int, keep: set[int]) -> None:
        worst, worst_index = 0.0, -1
        for index in range(first + 1, last):
            d = point_segment_distance(meters[index], meters[first], meters[last])
            if d > worst:
                worst, worst_index = d, index
        if worst > tolerance_m:
            keep.add(worst_index)
            walk(first, worst_index, keep)
            walk(worst_index, last, keep)

    keep = {0, len(points) - 1}
    # 왕복 경로는 시작점과 끝점이 같아 기준선이 없으므로 가장 먼 점에서 먼저 나눈다.
    middle = max(range(len(points)), key=lambda i: math.hypot(meters[i][0] - meters[0][0], meters[i][1] - meters[0][1]))
    if 0 < middle < len(points) - 1:
        keep.add(middle)
        walk(0, middle, keep)
        walk(middle, len(points) - 1, keep)
    else:
        walk(0, len(points) - 1, keep)
    return [points[i] for i in sorted(keep)]


def build(cache_dir: Path) -> list[dict]:
    facilities, missing = fetch_facilities(cache_dir)
    today = date.today().isoformat()
    built = []
    for definition in COURSES:
        waypoints = definition["waypoints"]
        route_data = route_for(waypoints)
        full_route = [[round(lat, 6), round(lng, 6)] for lng, lat in route_data["geometry"]["coordinates"]]
        distance_km = round(route_data["distance"] / 1000, 2)
        nearby = []
        for kind, points in facilities.items():
            if kind == "park":
                # 공원은 중심점이 경로에서 멀 수 있으므로 코스에 정의한 이름으로 찾는다.
                nearby.extend({"type": kind, **p} for p in points if p["name"] in definition["park_names"])
                continue
            radius = FACILITY_RADIUS_M.get(kind, DEFAULT_RADIUS_M)
            for point in points:
                if distance_to_route(point["lat"], point["lng"], full_route) <= radius:
                    nearby.append({"type": kind, **point})
        record = {key: value for key, value in definition.items() if key != "waypoints"}
        record.update(
            area="서울 마포구 망원동 일대",
            start_lat=full_route[0][0],
            start_lng=full_route[0][1],
            distance_km=distance_km,
            duration_min=max(10, round(distance_km / WALK_KMH * 60 / 5) * 5),
            route=simplify(full_route),
            pet_allowed=True,
            pet_rule_note=PET_RULE,
            facilities=nearby,
            data_sources={
                "route": f"OSRM 도보 경로 / OpenStreetMap ({today})",
                "facilities": f"OpenStreetMap Overpass ({today})",
                "facilities_unavailable": missing,
                "team_estimates": ["crowd_level", "shade_level", "lighting", "traffic_exposure", "surface_note", "difficulty", "pet_allowed"],
            },
        )
        built.append(record)
        print(f"{record['code']:<22} {distance_km:>5.2f}km {record['duration_min']:>3}분 경로점 {len(record['route']):>3}개 시설 {len(nearby)}곳")
        time.sleep(1)
    print("가져오지 못한 시설 종류:", missing or "없음")
    return built


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".osm_cache")
    args = parser.parse_args()
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    courses = build(args.cache_dir)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(courses, ensure_ascii=False, indent=1) + "\n")
    print(f"{len(courses)}개 코스 저장: {OUTPUT}")


if __name__ == "__main__":
    main()
