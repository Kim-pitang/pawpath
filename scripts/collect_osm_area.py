"""서비스 지역 주변의 OpenStreetMap 도로·나무·공원을 미리 받아 backend/app/data/osm_<지역>.json으로 저장한다.

생성한 산책 경로 후보를 평가할 때 요청 시점에 공용 Overpass 서버를 부르면 20~40초가 걸리고 자주 504가 난다
(2026-10-31 실측). 그래서 서비스 지역은 이 스크립트로 미리 받아 두고 서버는 파일만 읽는다.

사용법: python scripts/collect_osm_area.py mangwon --cache-dir /tmp/osm-cache
- 지역 중심에서 반경 약 3km 상자를 2km 타일로 나눠, 타일마다 도로/나무/공원을 따로 묻는다(쿼리 하나를 작게 유지).
- 받은 타일 응답은 --cache-dir에 저장해 두고 다시 실행하면 건너뛴다. 한 조각이라도 못 받으면 파일을 쓰지 않는다(빠진 길이 '길 없음'으로 읽히지 않게).
- 요청 사이 5초 이상 쉰다. 공용 서버를 오래 점유하지 않는다.
"""
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import SERVICE_AREAS  # noqa: E402
from app.services import environment_service as env  # noqa: E402

HALF_LAT = 0.027  # 약 3km
HALF_LNG = 0.034
TILES = 3
PAUSE_S = 5.0
REQUEST_TIMEOUT_S = 100.0
RETRIES = 3
USER_AGENT = "PawPath/1.0 (https://github.com/FickleBoBo/pawpath) one-off area extract"
KEEP_WAY_TAGS = ("highway", "lit", "surface")
KEEP_TREE_TAGS = ("natural", "landuse")
KEEP_PARK_TAGS = ("leisure",)

QUERIES = {
    "highway": 'way["highway"]({box});out tags geom;',
    "trees": '(way["natural"~"^(wood|tree_row|scrub)$"]({box});way["landuse"~"^(forest|meadow|village_green)$"]({box});node["natural"="tree"]({box}););out tags geom;',
    "parks": 'way["leisure"~"^(park|garden|dog_park)$"]({box});out tags geom;',
}


def tile_boxes(lat: float, lng: float) -> list[tuple[float, float, float, float]]:
    south, west = lat - HALF_LAT, lng - HALF_LNG
    dlat, dlng = 2 * HALF_LAT / TILES, 2 * HALF_LNG / TILES
    return [(south + r * dlat, west + c * dlng, south + (r + 1) * dlat, west + (c + 1) * dlng) for r in range(TILES) for c in range(TILES)]


def fetch(client: httpx.Client, query: str) -> list[dict] | None:
    for attempt in range(RETRIES):
        for url in env.OVERPASS_MIRRORS:
            try:
                response = client.post(url, data={"data": f"[out:json][timeout:90];{query}"})
                if response.status_code == 200:
                    return response.json()["elements"]
                print(f"    {url.split('/')[2]} HTTP {response.status_code}")
            except (httpx.HTTPError, ValueError, KeyError) as error:
                print(f"    {url.split('/')[2]} {type(error).__name__}")
            time.sleep(PAUSE_S)
        time.sleep(PAUSE_S * (attempt + 1) * 2)
    return None


def collect(area_key: str, cache_dir: Path) -> dict:
    area = SERVICE_AREAS[area_key]
    cache_dir.mkdir(parents=True, exist_ok=True)
    pieces: dict[str, dict[tuple, dict]] = {name: {} for name in QUERIES}
    failed = []
    with httpx.Client(timeout=REQUEST_TIMEOUT_S, headers={"User-Agent": USER_AGENT}) as client:
        for index, box in enumerate(tile_boxes(area.latitude, area.longitude)):
            text = ",".join(f"{v:.5f}" for v in box)
            for name, template in QUERIES.items():
                cached = cache_dir / f"{area_key}-{index}-{name}.json"
                if cached.exists():
                    elements = json.loads(cached.read_text())
                else:
                    print(f"[{area_key}] 타일 {index + 1}/{TILES * TILES} {name} 요청")
                    elements = fetch(client, template.format(box=text))
                    if elements is None:
                        failed.append(f"{index}-{name}")
                        continue
                    cached.write_text(json.dumps(elements))
                    time.sleep(PAUSE_S)
                for element in elements:
                    pieces[name][(element["type"], element["id"])] = element
    return {"pieces": pieces, "failed": failed, "area": area}


def compact_geometry(element: dict) -> list[list[float]]:
    return [[round(node["lat"], 5), round(node["lon"], 5)] for node in element.get("geometry") or []]


def build(result: dict) -> dict:
    ways, trees, parks = [], [], []
    for element in result["pieces"]["highway"].values():
        tags = element.get("tags", {})
        if "highway" in tags and element["type"] == "way" and len(element.get("geometry") or []) >= 2:
            ways.append([{k: tags[k] for k in KEEP_WAY_TAGS if k in tags}, compact_geometry(element)])
    tree_points = []
    for element in result["pieces"]["trees"].values():
        tags = element.get("tags", {})
        if element["type"] == "node":
            tree_points.append([round(element["lat"], 5), round(element["lon"], 5)])
        elif tags.get("natural") in env.TREE_NATURAL or tags.get("landuse") in env.TREE_LANDUSE:
            geometry = compact_geometry(element)
            if len(geometry) >= 2:
                trees.append([{k: tags[k] for k in KEEP_TREE_TAGS if k in tags}, geometry])
    for element in result["pieces"]["parks"].values():
        tags = element.get("tags", {})
        if tags.get("leisure") in env.PARK_LEISURE and element["type"] == "way":
            geometry = compact_geometry(element)
            if len(geometry) >= 4:
                parks.append([{k: tags[k] for k in KEEP_PARK_TAGS if k in tags}, geometry])
    area = result["area"]
    return {
        "collected_on": date.today().isoformat(),
        "source": "OpenStreetMap",
        "center": [area.latitude, area.longitude],
        "bbox": [area.latitude - HALF_LAT, area.longitude - HALF_LNG, area.latitude + HALF_LAT, area.longitude + HALF_LNG],
        "ways": ways,
        "tree_points": tree_points,
        "trees": trees,
        "parks": parks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("area", choices=sorted(SERVICE_AREAS))
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()
    result = collect(args.area, args.cache_dir)
    if result["failed"]:
        # 일부만 받은 자료로 파일을 만들면 빠진 길이 '길이 없는 곳'으로 읽힌다. 완전히 받을 때만 쓴다.
        print("받지 못한 조각이 있어 파일을 쓰지 않았어요(다시 실행하면 받은 조각은 건너뛰고 이어서 받아요):", sorted(result["failed"]))
        sys.exit(1)
    data = build(result)
    out = ROOT / "backend" / "app" / "data" / f"osm_{args.area}.json"
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"저장: {out} ({out.stat().st_size / 1e6:.1f}MB) 도로 {len(data['ways'])} 나무점 {len(data['tree_points'])} 숲/가로수 {len(data['trees'])} 공원 {len(data['parks'])}")


if __name__ == "__main__":
    main()
