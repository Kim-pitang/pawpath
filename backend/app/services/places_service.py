"""코스 주변 시설 검색. 미리 수집한 OSM 자료를 쓰므로 실행 중 외부 서비스에 의존하지 않는다."""
import json
import math
from functools import lru_cache
from pathlib import Path

from app.models import WalkingCourse

DATA_DIR = Path(__file__).parent.parent / "data"
PLACES_PATHS = (DATA_DIR / "places.json", DATA_DIR / "places_gaepo.json")

PLACE_LABELS = {
    "park": "공원",
    "dog_park": "반려견 놀이터",
    "veterinary": "동물병원",
    "pet_friendly": "반려동물 동반 표시 장소",
    "pet_shop": "반려용품점",
    "drinking_water": "음수대",
    "toilets": "화장실",
    "convenience": "편의점",
}
PET_ACCESS_NOTE = "OpenStreetMap 표시 기준이에요. 실제 동반 가능 여부는 방문 전에 확인해 주세요."
MAX_RESULTS = 40


@lru_cache
def load_places() -> dict:
    """지역별 자료를 합친다. 결과는 코스 경로와의 거리로 거르므로 다른 지역 장소는 나오지 않는다."""
    loaded = [json.loads(path.read_text(encoding="utf-8")) for path in PLACES_PATHS if path.exists()]
    if not loaded:
        return {"collected_on": None, "places": [], "unavailable_types": list(PLACE_LABELS)}
    return {
        "collected_on": max(data["collected_on"] for data in loaded),
        "source": "OpenStreetMap",
        "places": [place for data in loaded for place in data["places"]],
        "unavailable_types": sorted({kind for data in loaded for kind in data["unavailable_types"]}),
    }


def _distance_to_route_m(lat: float, lng: float, route: list[list[float]]) -> float:
    cos_lat = math.cos(math.radians(lat))
    to_local = lambda point: ((point[1] - lng) * 111320 * cos_lat, (point[0] - lat) * 110540)  # noqa: E731
    best = float("inf")
    for start, end in zip(route, route[1:]):
        ax, ay = to_local(start)
        bx, by = to_local(end)
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        t = 0.0 if length == 0 else max(0.0, min(1.0, (-ax * dx - ay * dy) / length))
        best = min(best, math.hypot(ax + dx * t, ay + dy * t))
    return best


def nearby_places(course: WalkingCourse, radius_m: int, types: set[str] | None = None) -> dict:
    data = load_places()
    results = []
    seen = set()
    for place in data["places"]:
        if types and place["type"] not in types:
            continue
        distance = _distance_to_route_m(place["lat"], place["lng"], course.route)
        if distance > radius_m:
            continue
        key = (place["type"], round(place["lat"], 5), round(place["lng"], 5))
        if key in seen:
            continue
        seen.add(key)
        results.append(
            {
                "type": place["type"],
                "label": PLACE_LABELS.get(place["type"], place["type"]),
                "name": place.get("name") or PLACE_LABELS.get(place["type"], place["type"]),
                "lat": place["lat"],
                "lng": place["lng"],
                "distance_m": round(distance),
                "note": PET_ACCESS_NOTE if place["type"] == "pet_friendly" else None,
            }
        )
    results.sort(key=lambda item: item["distance_m"])
    return {
        "course_id": course.id,
        "radius_m": radius_m,
        "source": "OpenStreetMap",
        "collected_on": data.get("collected_on"),
        "unavailable_types": [kind for kind in data.get("unavailable_types", []) if not types or kind in types],
        "notice": "지도에 기록된 장소만 보여 줘요. 없는 것처럼 보여도 실제로는 있을 수 있어요.",
        "places": results[:MAX_RESULTS],
    }
