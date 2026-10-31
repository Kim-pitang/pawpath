"""미리 뽑아 둔 OpenStreetMap 도로·나무·공원 타일.

scripts/extract_osm_tiles.py가 OSRM용 .osm.pbf에서 뽑아 backend/app/data/osm/<지역>/에 저장한 자료를 읽는다.
폴더마다 manifest.json(지역 범위·자료 날짜·타일 크기)과 tiles/<경도칸>_<위도칸>.json.gz가 있다.
요청 시점에 공용 Overpass 서버를 부르면 20~40초가 걸리고 자주 504가 나서(2026-10-31 실측) 경로 평가에 쓸 수 없었다.
지역 범위 밖의 경로는 측정하지 못하고, 호출한 쪽이 '확인 불가'로 다룬다. 범위 안인데 타일 파일이 없으면 그곳에 길이 없는 것이다(바다, 산).
"""
import gzip
import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data" / "osm"
TILE_CACHE_SIZE = 64  # 타일 하나는 풀어 놓으면 수십 MB가 될 수 있어 한꺼번에 많이 들고 있지 않는다.

Box = tuple[float, float, float, float]  # south, west, north, east


@dataclass(frozen=True)
class OsmArea:
    name: str
    collected_on: str
    box: Box
    tile_lat: float
    tile_lng: float
    directory: Path

    def contains(self, points: list[list[float]]) -> bool:
        south, west, north, east = self.box
        return all(south <= lat <= north and west <= lng <= east for lat, lng in points)

    def tile_keys(self, box: Box) -> list[tuple[int, int]]:
        south, west, north, east = box
        return [
            (ix, iy)
            for ix in range(math.floor(west / self.tile_lng), math.floor(east / self.tile_lng) + 1)
            for iy in range(math.floor(south / self.tile_lat), math.floor(north / self.tile_lat) + 1)
        ]

    def elements(self, box: Box) -> tuple[list[dict], list[dict], list[dict]]:
        """상자와 닿는 타일의 도로·나무·공원. 타일 경계에 걸친 길은 양쪽 타일에 있어 겹칠 수 있다(결과는 같다)."""
        ways: list[dict] = []
        trees: list[dict] = []
        parks: list[dict] = []
        for key in self.tile_keys(box):
            tile_ways, tile_trees, tile_parks = _tile(self.directory, key)
            ways += tile_ways
            trees += tile_trees
            parks += tile_parks
        return ways, trees, parks


def _geometry(points: list[list[float]]) -> list[dict]:
    return [{"lat": lat, "lon": lng} for lat, lng in points]


def _expand(data: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """저장 형식(좌표 쌍 목록)을 environment_service가 읽는 Overpass 요소 모양으로 푼다."""
    way = lambda tags, points: {"type": "way", "tags": tags, "geometry": _geometry(points)}  # noqa: E731
    ways = [way(tags, points) for tags, points in data["ways"]]
    trees = [{"type": "node", "lat": lat, "lon": lng, "tags": {"natural": "tree"}} for lat, lng in data["tree_points"]]
    trees += [way(tags, points) for tags, points in data["trees"]]
    parks = [way(tags, points) for tags, points in data["parks"]]
    return ways, trees, parks


@lru_cache(maxsize=TILE_CACHE_SIZE)
def _tile(directory: Path, key: tuple[int, int]) -> tuple[list[dict], list[dict], list[dict]]:
    path = directory / "tiles" / f"{key[0]}_{key[1]}.json.gz"
    if not path.is_file():
        return [], [], []
    return _expand(json.loads(gzip.decompress(path.read_bytes()).decode("utf-8")))


@lru_cache
def load_areas() -> tuple[OsmArea, ...]:
    areas = []
    for manifest in sorted(DATA_DIR.glob("*/manifest.json")):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        areas.append(
            OsmArea(
                name=data["region"],
                collected_on=data["collected_on"],
                box=tuple(data["bbox"]),  # type: ignore[arg-type]
                tile_lat=data["tile_lat"],
                tile_lng=data["tile_lng"],
                directory=manifest.parent,
            )
        )
    # 좁은 지역이 먼저 오게 한다. 서울이 경기 안에 있을 때 더 작은 파일을 쓴다.
    return tuple(sorted(areas, key=lambda a: (a.box[2] - a.box[0]) * (a.box[3] - a.box[1])))


def clear_cache() -> None:
    load_areas.cache_clear()
    _tile.cache_clear()


def area_for(points: list[list[float]]) -> OsmArea | None:
    """모든 점이 한 지역의 범위 안에 있을 때만 그 지역을 돌려준다. 걸쳐 있으면 측정하지 않는다."""
    return next((area for area in load_areas() if area.contains(points)), None)


def _bounds(element: dict) -> Box | None:
    geometry = element.get("geometry")
    if geometry:
        lats = [node["lat"] for node in geometry]
        lngs = [node["lon"] for node in geometry]
        return min(lats), min(lngs), max(lats), max(lngs)
    if "lat" in element and "lon" in element:
        return element["lat"], element["lon"], element["lat"], element["lon"]
    return None


def near(elements: list[dict], box: Box) -> list[dict]:
    """상자와 겹치는 요소만. 큰 공원처럼 꼭짓점이 상자 밖에 있어도 겹치면 남긴다."""
    south, west, north, east = box
    kept = []
    for element in elements:
        bounds = _bounds(element)
        if bounds and bounds[2] >= south and bounds[0] <= north and bounds[3] >= west and bounds[1] <= east:
            kept.append(element)
    return kept
