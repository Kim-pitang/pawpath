import json
from pathlib import Path

import pytest

from app.services import route_generator as rg
from app.services.route_generator import RouteGenerationError, generate
from app.services.routing_service import RoutedPath, RoutingUnavailable

SAMPLES = json.loads((Path(__file__).parent / "fixtures" / "route_generator" / "osrm_samples.json").read_text())
SAMPLE = {item["key"]: item for item in SAMPLES}
ORIGIN = (37.555869, 126.9105)


def path_of(sample: dict) -> RoutedPath:
    """저장해 둔 실제 OSRM 응답(경로·보정 거리)을 라우터 반환값으로 바꾼다."""
    return RoutedPath(
        points=[[lat, lng] for lng, lat in sample["coordinates"]],
        distance_m=sample["distance"],
        snap_distances_m=tuple(sample["snaps"]),
    )


class ScriptedRouter:
    """미리 정한 결과를 차례로 돌려주는 라우터. Exception이면 던진다."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[list[tuple[float, float]]] = []

    def route_via(self, points):
        self.calls.append(points)
        result = self.results[min(len(self.calls), len(self.results)) - 1]
        if isinstance(result, Exception):
            raise result
        return result


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def run(router, minutes=30):
    fake = FakeTime()
    result = generate(ORIGIN, minutes, router, sleep=fake.sleep, clock=fake.clock)
    return result, fake


def distinct_good(n: int) -> list[RoutedPath]:
    """목표(1800m)에 맞고 서로 겹치지 않는 경로 n개."""
    base = path_of(SAMPLE["mangwon-30-0"])
    same = RoutedPath(base.points, 1800.0, base.snap_distances_m)
    return [shifted(same, i * 0.05) for i in range(n)]


# ---------- 지표 ----------

def test_repeated_ratio_matches_known_shapes():
    a, b, c, d = [37.55, 126.9], [37.55, 126.901], [37.551, 126.901], [37.551, 126.9]
    assert rg.repeated_ratio([a, b, a]) == pytest.approx(0.5, abs=1e-9)
    assert rg.repeated_ratio([a, b, c, d, a]) == pytest.approx(0.0, abs=1e-9)


def test_repeated_ratio_of_a_degenerate_path_counts_as_fully_repeated():
    assert rg.repeated_ratio([[37.55, 126.9], [37.55, 126.9]]) == 1.0


@pytest.mark.parametrize("key", list(SAMPLE))
def test_real_osrm_samples_match_the_recorded_experiment(key):
    sample = SAMPLE[key]
    expected = sample["expected"]
    route = rg.evaluate(path_of(sample), sample["target_min"] * 60, expected["bearing"], expected["radius_m"])
    assert route.passes is expected["passes"]
    assert route.repeated_pct == pytest.approx(expected["repeated_pct"], abs=1.5)
    assert route.error_pct == pytest.approx(expected["error_pct"], abs=0.2)


def test_gate_rejects_each_failed_criterion():
    base = path_of(SAMPLE["mangwon-30-0"])
    target = SAMPLE["mangwon-30-0"]["target_min"] * 60

    def passes(**changes):
        path = RoutedPath(**{**base.__dict__, **changes})
        return rg.evaluate(path, target, 0, 450).passes

    assert passes() is True
    # 시간: 짧은 쪽 −20%, 긴 쪽 +50%
    assert passes(distance_m=target * 1.49) is True
    assert passes(distance_m=target * 1.51) is False
    assert passes(distance_m=target * 0.81) is True
    assert passes(distance_m=target * 0.79) is False
    # 공원·캠퍼스 안에서 출발해 가장 가까운 보행로가 60m 떨어진 경우(개포디지털혁신파크 실측)도 통과해야 한다
    assert passes(snap_distances_m=(59.9, 0.0, 0.0, 59.9)) is True
    assert passes(snap_distances_m=(151.0, 0.0, 0.0, 0.0)) is False  # 출발점 보정 150m 초과
    assert passes(snap_distances_m=(0.0, 151.0, 0.0, 0.0)) is False  # 경유점 보정 150m 초과
    assert passes(snap_distances_m=(150.0, 150.0, 150.0, 150.0)) is True  # 경계값은 통과
    assert passes(points=base.points[:-1] + [[base.points[-1][0] + 0.001, base.points[-1][1]]]) is False  # 복귀 오차


def test_identical_candidates_overlap_completely():
    route = rg.evaluate(path_of(SAMPLE["mangwon-30-0"]), 1800, 0, 450)
    assert rg.overlap_ratio(route, route) == pytest.approx(1.0)


# ---------- 생성 흐름 ----------

def test_waypoints_form_a_loop_around_the_origin():
    points = rg.waypoints(ORIGIN, 450, 0)
    assert points[0] == points[-1] == ORIGIN
    for lat, lng in points[1:3]:
        assert rg.haversine_m(ORIGIN, (lat, lng)) == pytest.approx(450, rel=0.01)


def test_all_eight_bearings_are_always_explored_before_choosing():
    router = ScriptedRouter(*distinct_good(8))
    result, _ = run(router)
    assert len(router.calls) == 8 == result.requests  # 후보가 충분해도 멈추지 않고 모두 본다
    assert len(result.candidates) == rg.MAX_RESULTS == 5
    assert len({tuple(round(v, 5) for v in c[1]) for c in router.calls}) == 8  # 8개 방위가 모두 다르다


def test_the_best_candidates_are_chosen_from_all_eight_not_the_first_ones_found():
    base = path_of(SAMPLE["mangwon-30-0"])
    # 앞쪽 방위일수록 목표에서 멀고, 마지막 방위의 경로가 가장 좋다.
    worse = [RoutedPath(shifted(base, i * 0.05).points, 1800.0 + (7 - i) * 60, base.snap_distances_m) for i in range(8)]
    result, _ = run(ScriptedRouter(*worse))
    distances = [c.distance_m for c in result.candidates]
    assert distances == sorted(distances)  # 점수 순(= 목표에 가까운 순)
    assert min(distances) == 1800.0  # 8번째에 나온 가장 좋은 후보가 포함된다


def test_too_few_diverse_candidates_do_not_stop_the_search():
    good = path_of(SAMPLE["mangwon-30-0"])
    router = ScriptedRouter(good)  # 여덟 후보가 똑같아 다양성 규칙으로 하나만 남는다
    result, _ = run(router)
    assert len(result.candidates) == 1
    assert len(router.calls) == 8  # 오차가 작아 보정은 하지 않는다


def test_requests_are_spaced_to_respect_the_public_server_limit():
    router = ScriptedRouter(*distinct_good(8))
    _, fake = run(router)
    assert fake.slept == [pytest.approx(rg.REQUEST_INTERVAL_S)] * 7


def test_corrections_are_capped_and_total_requests_never_exceed_the_limit():
    bad = path_of(SAMPLE["gaepo-10-90"])  # 오차가 크고 통과하지 못한다
    router = ScriptedRouter(bad)
    result, _ = run(router, minutes=20)
    assert len(router.calls) == rg.MAX_REQUESTS == result.requests == 4 + 4 + rg.MAX_CORRECTIONS


def test_correction_rescales_the_radius_toward_the_target():
    short = RoutedPath(points=[[37.55, 126.9], [37.551, 126.9], [37.55, 126.9]], distance_m=900.0, snap_distances_m=(0, 0, 0, 0))
    router = ScriptedRouter(short)
    run(router, minutes=30)  # 목표 1800m인데 900m만 나옴 → 반경 두 배
    first_radius = rg.haversine_m(router.calls[0][0], router.calls[0][1])
    corrected = rg.haversine_m(router.calls[8][0], router.calls[8][1])  # 앞의 8번은 방위 탐색
    assert corrected == pytest.approx(first_radius * 2, rel=0.02)


def test_no_passing_candidate_returns_empty_list_with_the_best_rejected():
    router = ScriptedRouter(path_of(SAMPLE["hangang-10-0"]))
    result, _ = run(router, minutes=20)
    assert result.candidates == []
    assert result.best_rejected is not None and result.best_rejected.passes is False


def test_partial_failure_keeps_the_candidates_that_arrived():
    good = path_of(SAMPLE["mangwon-30-0"])
    router = ScriptedRouter(good, RoutingUnavailable("ReadTimeout"), good, RoutingUnavailable("ReadTimeout"))
    result, _ = run(router)
    assert len(result.candidates) == 1  # 도착한 두 경로는 같아서 하나만 남는다
    assert result.requests == 6  # 이후 실패가 이어져 연속 3회에서 멈춘다


def test_stops_after_consecutive_failures_and_raises():
    router = ScriptedRouter(RoutingUnavailable("ConnectError"))
    with pytest.raises(RouteGenerationError):
        run(router)
    assert len(router.calls) == rg.MAX_FAILURES


def test_a_success_resets_the_consecutive_failure_count():
    good = path_of(SAMPLE["mangwon-30-0"])
    fail = RoutingUnavailable("ConnectError")
    router = ScriptedRouter(fail, fail, good, fail)
    result, _ = run(router)
    # 성공이 연속 실패 횟수를 0으로 되돌려, 세 번째 호출 뒤 네 번째와 그 뒤 두 번이 실패해야 멈춘다.
    assert result.requests == 6 and len(result.candidates) == 1


@pytest.mark.parametrize("minutes", [rg.MIN_MINUTES - 1, rg.MAX_MINUTES + 1])
def test_duration_outside_the_supported_range_is_rejected(minutes):
    with pytest.raises(ValueError):
        generate(ORIGIN, minutes, ScriptedRouter(path_of(SAMPLE["mangwon-30-0"])))


def test_total_time_limit_stops_further_requests():
    class SlowTime(FakeTime):
        def clock(self):
            self.now += 8  # 호출할 때마다 8초가 지난 것으로 본다.
            return self.now

    fake = SlowTime()
    router = ScriptedRouter(path_of(SAMPLE["mangwon-30-0"]))
    result = generate(ORIGIN, 30, router, sleep=fake.sleep, clock=fake.clock)
    assert len(router.calls) < 4
    assert result.requests == len(router.calls)


def shifted(path: RoutedPath, dlat: float) -> RoutedPath:
    """같은 모양의 경로를 위도 방향으로 옮긴다. 옮긴 거리가 크면 서로 겹치지 않는다."""
    return RoutedPath(points=[[lat + dlat, lng] for lat, lng in path.points], distance_m=path.distance_m, snap_distances_m=path.snap_distances_m)


def test_diverse_candidates_are_kept_up_to_the_limit_and_sorted_by_score():
    base = path_of(SAMPLE["mangwon-30-0"])
    paths = [RoutedPath(shifted(base, i * 0.05).points, 1800.0 + i * 60, base.snap_distances_m) for i in range(6)]
    result, _ = run(ScriptedRouter(*paths))
    assert len(result.candidates) == rg.MAX_RESULTS == 5
    scores = [c.score for c in result.candidates]
    assert scores == sorted(scores)
    assert [c.distance_m for c in result.candidates] == [1800.0, 1860.0, 1920.0, 1980.0, 2040.0]


def test_overlapping_candidates_are_dropped_but_distinct_ones_stay():
    base = path_of(SAMPLE["mangwon-30-0"])
    same = RoutedPath(base.points, 1800.0, base.snap_distances_m)
    far = shifted(same, 0.05)
    result, _ = run(ScriptedRouter(same, same, far, far))
    assert len(result.candidates) == 2


def test_candidate_without_snap_information_never_passes():
    base = path_of(SAMPLE["mangwon-30-0"])
    route = rg.evaluate(RoutedPath(base.points, 1800.0), 1800, 0, 450)
    assert route.passes is False


def test_zero_distance_does_not_crash_the_correction_and_radius_stays_bounded():
    zero = RoutedPath(points=[[37.55, 126.9], [37.5501, 126.9]], distance_m=0.0, snap_distances_m=(0, 0, 0, 0))
    router = ScriptedRouter(zero)
    result, _ = run(router)
    assert result.candidates == []
    first = rg.haversine_m(router.calls[0][0], router.calls[0][1])
    corrected = rg.haversine_m(router.calls[8][0], router.calls[8][1])
    assert corrected <= first * rg.MAX_CORRECTION * 1.02
    assert corrected == pytest.approx(first * rg.MAX_CORRECTION, rel=0.02)


def test_tiny_distance_scales_the_radius_by_at_most_the_cap():
    tiny = RoutedPath(points=[[37.55, 126.9], [37.5501, 126.9]], distance_m=5.0, snap_distances_m=(0, 0, 0, 0))
    router = ScriptedRouter(tiny)
    run(router)
    first = rg.haversine_m(router.calls[0][0], router.calls[0][1])
    corrected = rg.haversine_m(router.calls[8][0], router.calls[8][1])
    assert corrected == pytest.approx(first * rg.MAX_CORRECTION, rel=0.02)


def test_interval_zero_for_a_self_hosted_server_means_no_waiting():
    fake = FakeTime()
    result = generate(ORIGIN, 30, ScriptedRouter(*distinct_good(8)), sleep=fake.sleep, clock=fake.clock, interval_s=0)
    assert fake.slept == []
    assert result.requests == 8


def test_custom_total_time_limit_is_respected():
    class Slow(FakeTime):
        def clock(self):
            self.now += 3  # 호출할 때마다 3초
            return self.now

    fake = Slow()
    router = ScriptedRouter(path_of(SAMPLE["mangwon-30-0"]))
    generate(ORIGIN, 30, router, sleep=fake.sleep, clock=fake.clock, interval_s=0, max_total_s=5)
    assert len(router.calls) < 8


# ---------- 더 많은 모양 시도하기(자체 서버용 설정) ----------

def run_wide(router, **options):
    fake = FakeTime()
    options.setdefault("max_total_s", 600.0)  # 기본 30초 제한은 요청 약 27회(간격 1.1초)에서 걸린다
    result = generate(ORIGIN, 30, router, sleep=fake.sleep, clock=fake.clock, **options)
    return result, fake


def test_default_search_plan_is_the_eight_public_server_shapes():
    plan = rg.search_plan(8, (1.0,), (30,))
    assert [shape[0] for shape in plan] == [0, 90, 180, 270, 45, 135, 225, 315]  # 동서남북이 먼저
    assert {shape[1:] for shape in plan} == {(1.0, 30)}


def test_search_plan_multiplies_bearings_scales_and_spreads_with_the_base_shape_first():
    plan = rg.search_plan(16, (1.0, 0.8), (30, 45))
    assert len(plan) == 16 * 2 * 2 == len(set(plan))
    assert all(shape[1:] == (1.0, 30) for shape in plan[:16])  # 기본 모양을 먼저 다 본다
    assert [shape[0] for shape in plan[:4]] == [0, 90, 180, 270]


def test_more_requests_find_more_distinct_candidates():
    router = ScriptedRouter(*distinct_good(40))
    result, fake = run_wide(router, bearing_count=24, radius_scales=(1.0, 0.9), spreads=(30,), max_requests=48, max_results=20)
    assert result.requests == len(router.calls) == 48
    assert len(result.candidates) == 20  # 요청 수가 아니라 요청한 상한(max_results)에서 멈춘다
    assert fake.slept[0] == pytest.approx(rg.REQUEST_INTERVAL_S)


def test_request_limit_caps_the_search_even_when_the_plan_is_larger():
    router = ScriptedRouter(*distinct_good(12))
    result, _ = run_wide(router, bearing_count=36, max_requests=12)
    assert len(router.calls) == result.requests == 12


def test_expanded_search_uses_each_shape_once_and_varies_the_waypoints():
    router = ScriptedRouter(*distinct_good(30))
    run_wide(router, bearing_count=12, radius_scales=(1.0, 0.8), spreads=(30, 45), max_requests=48)
    shapes = {tuple(round(v, 5) for v in call[1]) for call in router.calls}
    assert len(router.calls) == 48 and len(shapes) == 48  # 같은 요청을 두 번 보내지 않는다


def test_selection_scales_to_many_candidates_without_recomputing_edges_per_pair():
    # 서로 다른 후보 200개를 고르는 데 걸리는 시간이 눈에 띄게 길어지지 않는다
    import time as _time

    router = ScriptedRouter(*distinct_good(60))
    started = _time.monotonic()
    result, _ = run_wide(router, bearing_count=72, max_requests=60, max_results=50)
    assert len(result.candidates) == 50
    assert _time.monotonic() - started < 5


def test_default_total_time_limit_stops_a_large_plan_early():
    """시도를 늘릴 때 GENERATION_MAX_SECONDS를 함께 올리지 않으면 계획의 일부만 시도한다."""
    router = ScriptedRouter(*distinct_good(60))
    fake = FakeTime()
    result = generate(ORIGIN, 30, router, sleep=fake.sleep, clock=fake.clock, bearing_count=72, max_requests=60, max_results=50)
    assert 20 < result.requests < 60
