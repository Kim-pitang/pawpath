"""생성한 경로 후보를 반려동물·날씨·환경으로 평가해 순서를 매기는 부분."""
import json

import pytest

from app import api
from app.main import app
from app.services import osm_area_service, route_fit_service
from app.services import route_generator as rg
from app.services.routing_service import RoutedPath
from tests.test_generate_route_api import BODY, FakeViaRouter, path_of

# 같은 경로를 두 번 돌려주면 후보 1개만 남으므로, 서로 겹치지 않는 두 경로를 번갈아 돌려주는 라우터를 쓴다.


def shifted(path: RoutedPath, lng_offset: float) -> RoutedPath:
    """같은 모양을 옆으로 옮긴 경로. 시간·반복·보정 기준은 그대로 통과하고 앞 경로와는 겹치지 않는다."""
    return RoutedPath(points=[[lat, lng + lng_offset] for lat, lng in path.points], distance_m=path.distance_m, snap_distances_m=path.snap_distances_m)


class TwoRoutes:
    def __init__(self):
        base = path_of("mangwon-30-0")
        self.paths = [base, shifted(base, 0.0004)]
        self.calls = 0

    def route_via(self, points):
        path = self.paths[self.calls % len(self.paths)]
        self.calls += 1
        return path


@pytest.fixture
def install(client, monkeypatch):
    monkeypatch.setattr(rg.time, "sleep", lambda seconds: None)

    def go(router):
        app.dependency_overrides[api.generation_router] = lambda: router
        app.dependency_overrides[api.generation_gate] = lambda: rg.GenerationGate(cooldown_s=0)
        return client

    yield go
    app.dependency_overrides.pop(api.generation_router, None)
    app.dependency_overrides.pop(api.generation_gate, None)


def environment(park: float, major: float, trees: float, lit: float = 0.8) -> dict:
    return {
        "collected_on": "2026-10-31",
        "sampled_points": 100,
        "road": {"pedestrian": 1 - major, "local": 0.0, "major": major, "unknown": 0.0},
        "lit": {"yes": lit, "no": 1 - lit, "unknown": 0.0},
        "surface": {"paved": 1.0, "unpaved": 0.0, "unknown": 0.0},
        "trees": trees,
        "park": park,
    }


def test_without_a_pet_candidates_have_no_fit(install):
    client = install(FakeViaRouter(path_of("mangwon-30-0")))
    data = client.post("/api/routes/generate", json=BODY).json()
    assert data["scored_for"] is None
    assert all(c["fit"] is None for c in data["candidates"])


def test_with_a_pet_each_candidate_gets_a_score_and_reasons(install, monkeypatch):
    monkeypatch.setattr(route_fit_service, "measure_candidates", lambda routes: [environment(0.4, 0.0, 0.5)] * len(routes))
    client = install(FakeViaRouter(path_of("mangwon-30-0")))
    data = client.post("/api/routes/generate", json={**BODY, "pet_id": 1, "weather_scenario": "rain_later"}).json()
    assert data["scored_for"]
    fit = data["candidates"][0]["fit"]
    assert 0 <= fit["score"] <= 100
    assert fit["summary"] and fit["start_label"]
    assert any("공원" in line for line in fit["highlights"])


def test_a_park_route_away_from_traffic_ranks_above_a_busy_road_route(install, monkeypatch):
    by_call = iter([environment(0.0, 0.7, 0.0), environment(0.6, 0.0, 0.6)])
    monkeypatch.setattr(route_fit_service, "measure_candidates", lambda routes: [next(by_call) for _ in routes])
    client = install(TwoRoutes())
    data = client.post("/api/routes/generate", json={**BODY, "pet_id": 1}).json()
    scores = [c["fit"]["score"] for c in data["candidates"]]
    assert len(scores) == 2
    assert scores == sorted(scores, reverse=True) and scores[0] > scores[1]
    assert any("공원" in line for line in data["candidates"][0]["fit"]["highlights"])


def test_unmeasured_environment_is_marked_unknown_not_safe(install, monkeypatch):
    monkeypatch.setattr(route_fit_service, "measure_candidates", lambda routes: [None] * len(routes))
    client = install(FakeViaRouter(path_of("mangwon-30-0")))
    data = client.post("/api/routes/generate", json={**BODY, "pet_id": 1}).json()
    fit = data["candidates"][0]["fit"]
    assert {"traffic_exposure", "shade_level"} <= set(fit["unknown"])
    assert not any("큰 도로" in line or "나무" in line for line in fit["highlights"])
    assert "확인 불가" in data["fit_notice"]


def test_unknown_pet_is_a_404_and_does_not_use_the_routing_server(install):
    router = FakeViaRouter(path_of("mangwon-30-0"))
    client = install(router)
    response = client.post("/api/routes/generate", json={**BODY, "pet_id": 9999})
    assert response.status_code == 404
    assert router.calls == 0


@pytest.fixture
def area_file(tmp_path, monkeypatch):
    """작은 지역 자료 파일을 data 폴더 대신 쓴다. 저장 형식은 scripts/collect_osm_area.py가 쓰는 것과 같다."""

    def write(bbox):
        data = {
            "collected_on": "2026-10-30",
            "source": "OpenStreetMap",
            "center": [0, 0],
            "bbox": bbox,
            "ways": [[{"highway": "footway", "lit": "yes", "surface": "asphalt"}, [[37.5560, 126.9100], [37.5570, 126.9120]]]],
            "tree_points": [],
            "trees": [],
            # 꼭짓점이 경로 상자 밖에 있는 큰 공원
            "parks": [[{"leisure": "park"}, [[37.5550, 126.9090], [37.5550, 126.9130], [37.5580, 126.9130], [37.5580, 126.9090], [37.5550, 126.9090]]]],
        }
        (tmp_path / "osm_test.json").write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr(osm_area_service, "DATA_DIR", tmp_path)
        osm_area_service.load_areas.cache_clear()

    yield write
    osm_area_service.load_areas.cache_clear()


ROUTE = [[37.5560, 126.9100], [37.5565, 126.9110], [37.5570, 126.9120]]


def test_measure_candidates_uses_the_collected_area_and_picks_up_a_big_park(area_file):
    area_file([37.54, 126.89, 37.57, 126.93])
    measured = route_fit_service.measure_candidates([ROUTE, ROUTE])
    assert measured[0]["park"] == 1.0
    assert measured[0]["road"]["pedestrian"] == 1.0
    assert measured[0]["collected_on"] == "2026-10-30"  # 측정 날짜가 아니라 자료를 받은 날짜를 적는다


def test_route_outside_the_collected_area_is_unknown_not_guessed(area_file):
    area_file([37.54, 126.89, 37.5565, 126.93])  # 경로 일부가 상자 밖
    assert route_fit_service.measure_candidates([ROUTE]) == [None]


def test_no_collected_area_files_means_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(osm_area_service, "DATA_DIR", tmp_path)
    osm_area_service.load_areas.cache_clear()
    try:
        assert route_fit_service.measure_candidates([ROUTE]) == [None]
    finally:
        osm_area_service.load_areas.cache_clear()


def test_wider_pool_is_scored_then_cut_to_the_best_results(install, monkeypatch):
    """평가 전에는 넉넉히 만들고, 엔진 점수 순으로 화면에 줄 개수만 남긴다."""
    settings = api.get_settings()
    monkeypatch.setattr(settings, "generation_bearings", 12)
    monkeypatch.setattr(settings, "generation_max_requests", 12)
    monkeypatch.setattr(settings, "generation_pool_size", 12)
    monkeypatch.setattr(settings, "generation_max_results", 3)
    seen = {}

    def measure(routes):
        seen["pool"] = len(routes)
        # 뒤쪽 후보일수록 환경이 좋다 → 뒤쪽이 앞으로 와야 한다
        return [environment(0.0, 0.7 - 0.05 * i, 0.0) for i in range(len(routes))]

    monkeypatch.setattr(route_fit_service, "measure_candidates", measure)

    class Many:
        def __init__(self):
            self.calls = 0

        def route_via(self, points):
            self.calls += 1
            return shifted(path_of("mangwon-30-0"), 0.001 * self.calls)

    router = Many()
    client = install(router)
    data = client.post("/api/routes/generate", json={**BODY, "pet_id": 1}).json()
    assert router.calls == 12
    assert seen["pool"] == 12  # 평가는 넉넉한 후보 전체에 한다
    assert len(data["candidates"]) == 3  # 화면에는 상위만
    scores = [c["fit"]["score"] for c in data["candidates"]]
    assert scores == sorted(scores, reverse=True)


def test_without_a_pet_results_are_cut_to_max_results_by_route_quality(install, monkeypatch):
    settings = api.get_settings()
    monkeypatch.setattr(settings, "generation_max_results", 2)
    client = install(TwoRoutes())
    data = client.post("/api/routes/generate", json=BODY).json()
    assert len(data["candidates"]) <= 2


@pytest.mark.parametrize(
    "field,value",
    [("generation_radius_scales", "0.2"), ("generation_radius_scales", "a,b"), ("generation_radius_scales", "1.0,1.0"), ("generation_spreads", "5"), ("generation_spreads", "")],
)
def test_bad_generation_settings_are_rejected_when_the_server_starts(field, value):
    from app.config import Settings

    with pytest.raises(ValueError):
        Settings(**{field: value})
