"""OSM 지역 추출본(.osm.pbf)에서 도로·나무·공원을 뽑아 backend/app/data/osm/<지역>/ 타일 파일로 저장한다.

공용 Overpass 서버는 느리고 자주 504가 나서(2026-10-31 실측: 지역 하나에 46분) 서버가 요청 시점에도, 미리 받을 때도 쓰기 어려웠다.
OSRM에 쓰는 pbf(.osm_cache/osrm-*/)가 이미 같은 원본이라 거기서 뽑는다. 분 단위로 끝나고 pbf 범위 전체를 덮는다.

사용법: python scripts/extract_osm_tiles.py seoul .osm_cache/osrm-seoul/seoul.osm.pbf --source .osm_cache/osrm-seoul/south-korea-latest.osm.pbf
- 필요: osmium-tool(`brew install osmium-tool`). 파이썬 패키지는 더 필요 없다.
- 지역 범위는 pbf 헤더의 bbox다. 그 밖은 서버가 '확인 불가'로 다룬다.
- 타일 크기를 바꾸면 manifest의 값도 함께 바뀌므로 서버는 그대로 읽는다.
- 데이터 날짜는 --source pbf(Geofabrik 원본)의 replication timestamp다. 자르면 헤더가 지워져서 원본을 따로 받는다.
- 결과 폴더는 매번 새로 만든다(이전 타일이 남아 섞이지 않게).
"""
import argparse
import gzip
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "backend" / "app" / "data" / "osm"

TILE_LAT = 0.02  # 약 2.2km
TILE_LNG = 0.025
KEEP_WAY_TAGS = ("highway", "lit", "surface")
KEEP_TREE_TAGS = ("natural", "landuse")
KEEP_PARK_TAGS = ("leisure",)
TREE_NATURAL = {"wood", "tree_row", "scrub"}
TREE_LANDUSE = {"forest", "meadow", "village_green"}
PARK_LEISURE = {"park", "garden", "dog_park"}


def run(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()


def header(pbf: Path, field: str) -> str:
    return run("osmium", "fileinfo", "-g", field, str(pbf))


def filtered_features(pbf: Path, work: Path, name: str, expressions: list[str], geometry_types: str):
    """태그로 거른 pbf를 GeoJSON 줄 단위로 돌려준다. 필요한 모양(선/면/점)만 받는다."""
    filtered = work / f"{name}.osm.pbf"
    exported = work / f"{name}.geojsonseq"
    run("osmium", "tags-filter", "-o", str(filtered), "--overwrite", str(pbf), *expressions)
    run("osmium", "export", "-f", "geojsonseq", "-x", "print_record_separator=false", f"--geometry-types={geometry_types}", "--overwrite", "-o", str(exported), str(filtered))
    with exported.open(encoding="utf-8") as lines:
        for line in lines:
            if line.strip():
                yield json.loads(line)


def rounded(points) -> list[list[float]]:
    """GeoJSON은 [경도, 위도]다. 앱은 [위도, 경도]로 쓴다."""
    return [[round(lat, 5), round(lng, 5)] for lng, lat in points]


def line_of(geometry: dict) -> list[list[float]] | None:
    kind = geometry["type"]
    if kind == "LineString":
        return rounded(geometry["coordinates"])
    if kind == "Polygon":  # 닫힌 길. 바깥 고리만 쓴다(기존 Overpass 자료의 닫힌 way와 같다).
        return rounded(geometry["coordinates"][0])
    return None


def tile_keys(points: list[list[float]]) -> set[tuple[int, int]]:
    lats = [p[0] for p in points]
    lngs = [p[1] for p in points]
    return {
        (ix, iy)
        for ix in range(math.floor(min(lngs) / TILE_LNG), math.floor(max(lngs) / TILE_LNG) + 1)
        for iy in range(math.floor(min(lats) / TILE_LAT), math.floor(max(lats) / TILE_LAT) + 1)
    }


def pick(tags: dict, keys: tuple[str, ...]) -> dict:
    return {key: tags[key] for key in keys if key in tags}


def collect(pbf: Path, work: Path) -> dict[tuple[int, int], dict[str, list]]:
    tiles: dict[tuple[int, int], dict[str, list]] = defaultdict(lambda: {"ways": [], "tree_points": [], "trees": [], "parks": []})

    for feature in filtered_features(pbf, work, "highway", ["w/highway"], "linestring,polygon"):
        points = line_of(feature["geometry"])
        if points and len(points) >= 2:
            way = [pick(feature["properties"], KEEP_WAY_TAGS), points]
            for key in tile_keys(points):
                tiles[key]["ways"].append(way)

    for feature in filtered_features(pbf, work, "trees", ["n/natural=tree", "w/natural=wood,tree_row,scrub", "w/landuse=forest,meadow,village_green"], "point,linestring,polygon"):
        tags = feature["properties"]
        geometry = feature["geometry"]
        if geometry["type"] == "Point":
            lng, lat = geometry["coordinates"]
            point = [round(lat, 5), round(lng, 5)]
            tiles[(math.floor(point[1] / TILE_LNG), math.floor(point[0] / TILE_LAT))]["tree_points"].append(point)
        elif tags.get("natural") in TREE_NATURAL or tags.get("landuse") in TREE_LANDUSE:
            points = line_of(geometry)
            if points and len(points) >= 2:
                tree = [pick(tags, KEEP_TREE_TAGS), points]
                for key in tile_keys(points):
                    tiles[key]["trees"].append(tree)

    for feature in filtered_features(pbf, work, "parks", ["w/leisure=park,garden,dog_park"], "linestring,polygon"):
        tags = feature["properties"]
        points = line_of(feature["geometry"])
        # 면적이 있는 공원만. 닫히지 않은 길은 공원 안 판정에 쓸 수 없다.
        if tags.get("leisure") in PARK_LEISURE and points and len(points) >= 4 and points[0] == points[-1]:
            park = [pick(tags, KEEP_PARK_TAGS), points]
            for key in tile_keys(points):
                tiles[key]["parks"].append(park)
    return tiles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("region", help="저장 폴더 이름(예: seoul, gyeonggi, korea)")
    parser.add_argument("pbf", type=Path, help="지역 추출본 .osm.pbf")
    parser.add_argument("--source", type=Path, help="자르기 전 원본 pbf. 데이터 날짜를 여기서 읽는다")
    args = parser.parse_args()

    if not re.fullmatch(r"[a-z0-9_]+", args.region):
        sys.exit("region은 영소문자·숫자·밑줄만 쓸 수 있어요(폴더를 통째로 지우는 경로이므로).")
    if not shutil.which("osmium"):
        sys.exit("osmium-tool이 필요해요: brew install osmium-tool")
    if not args.pbf.is_file():
        sys.exit(f"pbf를 찾을 수 없어요: {args.pbf}")
    boxes = header(args.pbf, "header.boxes")
    if not boxes:
        sys.exit("pbf 헤더에 bbox가 없어요. osmium extract --set-bounds로 자른 파일을 쓰세요.")
    west, south, east, north = (float(v) for v in boxes.strip("()").split(","))
    stamp = header(args.source or args.pbf, "header.option.osmosis_replication_timestamp")
    if not stamp:
        sys.exit("데이터 날짜(osmosis_replication_timestamp)를 pbf 헤더에서 못 찾았어요. 자르기 전 원본을 --source로 주세요.")

    out = OUT_ROOT / args.region
    with tempfile.TemporaryDirectory() as tmp:
        tiles = collect(args.pbf, Path(tmp))
    if out.exists():
        shutil.rmtree(out)
    (out / "tiles").mkdir(parents=True)
    total = 0
    for (ix, iy), content in tiles.items():
        data = gzip.compress(json.dumps(content, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), compresslevel=9, mtime=0)
        (out / "tiles" / f"{ix}_{iy}.json.gz").write_bytes(data)
        total += len(data)
    manifest = {
        "region": args.region,
        "source": "OpenStreetMap (Geofabrik 추출본)",
        "collected_on": stamp[:10],
        "bbox": [south, west, north, east],
        "tile_lat": TILE_LAT,
        "tile_lng": TILE_LNG,
        "tile_count": len(tiles),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"저장: {out} 타일 {len(tiles)}개, 합계 {total / 1e6:.1f}MB, 자료 날짜 {manifest['collected_on']}, 범위 {manifest['bbox']}")


if __name__ == "__main__":
    main()
