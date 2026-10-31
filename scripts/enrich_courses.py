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

사용법: python3 scripts/enrich_courses.py <입력 폴더> [--area gaepo]
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
# 계산은 앱과 같은 모듈을 쓴다. 내 산책길을 추천 후보로 등록할 때도 같은 기준으로 측정한다.
from app.services.environment_service import (  # noqa: E402
    measure_parks,
    measure_roads,
    measure_trees,
    prepared_ways,
    sample_route,
)
DATA_DIR = ROOT / "backend" / "app" / "data"
AREA_FILES = {
    "mangwon": (DATA_DIR / "courses.json", DATA_DIR / "places.json"),
    "gaepo": (DATA_DIR / "courses_gaepo.json", DATA_DIR / "places_gaepo.json"),
}

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


def load_elements(folder: Path, name: str) -> list[dict] | None:
    path = folder / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))["elements"] if path.exists() else None


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--area", choices=AREA_FILES, default="mangwon")
    args = parser.parse_args()
    folder = args.folder
    courses_path, places_path = AREA_FILES[args.area]
    today = date.today().isoformat()
    courses = json.loads(courses_path.read_text(encoding="utf-8"))
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
    courses_path.write_text(json.dumps(courses, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    places = build_places(folder, today)
    places_path.write_text(json.dumps(places, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    counts: dict[str, int] = {}
    for place in places["places"]:
        counts[place["type"]] = counts.get(place["type"], 0) + 1
    print("시설:", counts, "/ 못 받은 종류:", places["unavailable_types"] or "없음")


if __name__ == "__main__":
    main()
