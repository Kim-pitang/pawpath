"""서비스 지역 주변의 미리 수집한 OpenStreetMap 도로·나무·공원.

scripts/collect_osm_area.py가 backend/app/data/osm_<지역>.json으로 저장한 자료를 읽는다.
요청 시점에 공용 Overpass 서버를 부르면 20~40초가 걸리고 자주 504가 나서(2026-10-31 실측) 경로 평가에 쓸 수 없었다.
자료가 덮는 상자 밖의 경로는 측정하지 못하고, 호출한 쪽이 '확인 불가'로 다룬다.
"""
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

Box = tuple[float, float, float, float]  # south, west, north, east


@dataclass(frozen=True)
class OsmArea:
    collected_on: str
    box: Box
    ways: list[dict]
    trees: list[dict]
    parks: list[dict]

    def contains(self, points: list[list[float]]) -> bool:
        south, west, north, east = self.box
        return all(south <= lat <= north and west <= lng <= east for lat, lng in points)


def _geometry(points: list[list[float]]) -> list[dict]:
    return [{"lat": lat, "lon": lng} for lat, lng in points]


def _expand(data: dict) -> OsmArea:
    """저장 형식(좌표 쌍 목록)을 environment_service가 읽는 Overpass 요소 모양으로 푼다."""
    way = lambda tags, points: {"type": "way", "tags": tags, "geometry": _geometry(points)}  # noqa: E731
    return OsmArea(
        collected_on=data["collected_on"],
        box=tuple(data["bbox"]),  # type: ignore[arg-type]
        ways=[way(tags, points) for tags, points in data["ways"]],
        trees=[{"type": "node", "lat": lat, "lon": lng, "tags": {"natural": "tree"}} for lat, lng in data["tree_points"]]
        + [way(tags, points) for tags, points in data["trees"]],
        parks=[way(tags, points) for tags, points in data["parks"]],
    )


@lru_cache
def load_areas() -> tuple[OsmArea, ...]:
    return tuple(_expand(json.loads(path.read_text(encoding="utf-8"))) for path in sorted(DATA_DIR.glob("osm_*.json")))


def area_for(points: list[list[float]]) -> OsmArea | None:
    """모든 점이 한 지역 자료 상자 안에 있을 때만 그 지역을 돌려준다. 걸쳐 있으면 측정하지 않는다."""
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
