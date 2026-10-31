"""출발점과 원하는 산책 시간만으로 순환 경로를 만든다.

출발점에서 방향이 다른 경유점 두 개를 잡아 도보 라우터에 한 번에 요청하면 출발점으로 돌아오는 고리가 나온다.
공용 OSRM 도보 서버로 12개 조건을 실측한 결과(experiments/generated-walks)에서 정한 방식과 기준이다.
- 방위 8개(45° 간격)를 모두 한 번씩 요청한 뒤 좋은 후보를 고른다. 후보가 5개에 못 미치면 시간 오차가 큰 후보의 반경을 후보마다 한 번만 보정한다(요청 최대 11회).
- 공용 서버 정책(초당 1회)에 맞춰 요청 사이를 띄운다.
- 기준을 넘지 못한 후보는 내놓지 않는다. 걸맞은 후보가 없으면 빈 목록을 돌려준다.
통과 기준은 실험용 선택이다. 이 모듈은 길이·시간·반복만 본다. 반려견·날씨·주변 환경에 맞는지는 route_fit_service가 따로 평가한다.
위치는 계산에만 쓰고 저장하거나 로그에 남기지 않는다.
"""
import collections
import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from app.services.routing_service import LatLng, RoutedPath, RoutingUnavailable, WALK_METERS_PER_MIN, haversine_m

logger = logging.getLogger(__name__)

MIN_MINUTES = 20  # 실측에서 10분 목표는 12개 조건 중 4곳이 통과 후보 0개였다.
MAX_MINUTES = 90
BEARINGS = (0, 90, 180, 270)
EXTRA_BEARINGS = (45, 135, 225, 315)  # 8방향을 모두 본 뒤 좋은 후보를 고른다.
SPREAD_DEG = 30  # 경유점 두 개가 기준 방위 양옆으로 벌어지는 각도
MAX_CORRECTIONS = 3  # 시간 오차가 큰 후보의 반경을 고쳐 다시 요청하는 횟수(후보마다 한 번)
MAX_REQUESTS = 11  # 방위 8개 + 보정 3회. 보정은 후보가 모자랄 때만 한다.
REQUEST_INTERVAL_S = 1.1  # 공용 서버는 초당 1회를 넘지 말라고 안내한다.
MAX_TOTAL_S = 30.0  # 이 시간을 넘기면 남은 요청을 보내지 않고 지금까지의 후보로 마친다.
MAX_FAILURES = 3  # 연속으로 이만큼 실패하면 서버를 더 두드리지 않는다.
MAX_CORRECTION = 2.0  # 보정 때 반경을 바꿀 수 있는 최대 배율(또는 그 역수)
CORRECT_ABOVE = 0.10  # 최선 후보의 시간 오차가 이를 넘으면 보정한다.

# 통과 기준. 처음 정한 값(오차 ±20%, 보정 30m/75m)은 실측 12개 조건만 본 것이었다. 공원·캠퍼스·단지 안에서는
# 가장 가까운 보행로까지 60m 이상이 흔해서 후보가 전부 탈락했다(개포디지털혁신파크 실측).
# 시간은 짧은 쪽을 더 엄격하게 본다. 목표보다 길면 보호자가 고르면 되지만 너무 짧으면 산책이 안 된다.
MAX_UNDER = 0.20
MAX_OVER = 0.50
MAX_REPEAT = 0.25
MAX_START_SNAP_M = 150.0
MAX_VIA_SNAP_M = 150.0
MAX_CLOSURE_M = 5.0
MAX_CANDIDATE_OVERLAP = 0.65
MAX_RESULTS = 5

EdgeKey = tuple


class ViaRouter(Protocol):
    def route_via(self, points: list[LatLng]) -> RoutedPath: ...


class RouteGenerationError(Exception):
    """길찾기 서버에서 경로를 하나도 받지 못했다."""


@dataclass(frozen=True)
class GeneratedRoute:
    points: list[list[float]]
    distance_m: float
    duration_min: float
    error_pct: float
    repeated_pct: float
    start_snap_m: float
    max_via_snap_m: float
    closure_m: float
    score: float
    passes: bool
    bearing: int
    radius_m: float
    spread_deg: int = SPREAD_DEG


@dataclass(frozen=True)
class GenerationResult:
    candidates: list[GeneratedRoute]  # 통과한 후보를 점수 순으로, 서로 많이 겹치지 않게 최대 MAX_RESULTS개
    requests: int
    best_rejected: GeneratedRoute | None  # 통과 후보가 없을 때 왜 안 됐는지 보여 주기 위한 최선 후보


def _offset(origin: LatLng, bearing_deg: float, distance_m: float) -> LatLng:
    lat, lng = origin
    angle = math.radians(bearing_deg)
    return (
        lat + distance_m * math.cos(angle) / 111_320,
        lng + distance_m * math.sin(angle) / (111_320 * math.cos(math.radians(lat))),
    )


def waypoints(origin: LatLng, radius_m: float, bearing: float, spread_deg: float = SPREAD_DEG) -> list[LatLng]:
    return [
        origin,
        _offset(origin, bearing - spread_deg, radius_m),
        _offset(origin, bearing + spread_deg, radius_m),
        origin,
    ]


def _edges(points: list[list[float]]) -> tuple[dict[EdgeKey, float], collections.Counter]:
    """방향 없는 구간별 한 번 지나는 길이(m)와 지나간 횟수.

    도로 ID가 아니라 좌표(약 0.1m)로 구간을 구분하는 근사라서, 다르게 쪼개졌거나 나란한 길은 놓칠 수 있다.
    """
    lengths: dict[EdgeKey, float] = {}
    counts: collections.Counter = collections.Counter()
    for a, b in zip(points, points[1:]):
        key = tuple(sorted((tuple(round(v, 6) for v in a), tuple(round(v, 6) for v in b))))
        lengths.setdefault(key, haversine_m(tuple(a), tuple(b)))
        counts[key] += 1
    return lengths, counts


def edge_lengths(points: list[list[float]]) -> dict[EdgeKey, float]:
    """구간별로 지나간 총 길이(m). 같은 구간을 두 번 지나면 두 배가 된다."""
    lengths, counts = _edges(points)
    return {key: length * counts[key] for key, length in lengths.items()}


def repeated_ratio(points: list[list[float]]) -> float:
    """경로 길이 중 같은 구간을 다시 지나는 비율. 순수 왕복은 0.5, 겹침 없는 고리는 0."""
    lengths, counts = _edges(points)
    total = sum(length * counts[key] for key, length in lengths.items())
    if total == 0:
        return 1.0
    return max(0.0, 1 - sum(lengths.values()) / total)


def _shared_ratio(ea: dict[EdgeKey, float], eb: dict[EdgeKey, float]) -> float:
    shared = sum(min(length, eb.get(edge, 0.0)) for edge, length in ea.items())
    return shared / min(sum(ea.values()), sum(eb.values()))


def overlap_ratio(a: GeneratedRoute, b: GeneratedRoute) -> float:
    """두 후보가 공유하는 길이를 더 짧은 쪽 길이로 나눈 값."""
    return _shared_ratio(edge_lengths(a.points), edge_lengths(b.points))


def evaluate(path: RoutedPath, target_m: float, bearing: int, radius_m: float, spread_deg: int = SPREAD_DEG) -> GeneratedRoute:
    signed_error = (path.distance_m - target_m) / target_m
    error = abs(signed_error)
    repeat = repeated_ratio(path.points)
    snaps = path.snap_distances_m
    has_snaps = len(snaps) == 4  # 출발-A-B-출발. 보정 거리를 모르면 기준을 확인할 수 없으니 통과시키지 않는다.
    start_snap = snaps[0] if snaps else 0.0
    via_snap = max(snaps[1:-1], default=0.0) if len(snaps) > 2 else 0.0
    closure = haversine_m(tuple(path.points[0]), tuple(path.points[-1]))  # type: ignore[arg-type]
    return GeneratedRoute(
        points=path.points,
        distance_m=round(path.distance_m, 1),
        duration_min=round(path.distance_m / WALK_METERS_PER_MIN, 1),
        error_pct=round(error * 100, 1),
        repeated_pct=round(repeat * 100, 1),
        start_snap_m=round(start_snap, 1),
        max_via_snap_m=round(via_snap, 1),
        closure_m=round(closure, 2),
        score=round(error * 3 + repeat * 2 + min(2.0, start_snap / 50), 4),
        passes=(
            has_snaps
            and -MAX_UNDER <= signed_error <= MAX_OVER
            and repeat <= MAX_REPEAT
            and start_snap <= MAX_START_SNAP_M
            and via_snap <= MAX_VIA_SNAP_M
            and closure <= MAX_CLOSURE_M
        ),
        bearing=bearing,
        radius_m=round(radius_m, 1),
        spread_deg=spread_deg,
    )


def search_plan(bearing_count: int, radius_scales: tuple[float, ...], spreads: tuple[int, ...]) -> list[tuple[int, float, int]]:
    """시도할 (방위, 반경 배율, 벌어짐 각도) 목록. 동서남북 기본 모양을 먼저 두어, 서버가 안 되는지 빨리 알 수 있게 한다."""
    bearings = sorted({round(i * 360 / bearing_count) % 360 for i in range(bearing_count)}, key=lambda b: (b % 90 != 0, b))
    base = (radius_scales[0], spreads[0])
    shapes = [(b, base[0], base[1]) for b in bearings]
    shapes += [(b, scale, spread) for scale in radius_scales for spread in spreads for b in bearings if (scale, spread) != base]
    return shapes


def generate(
    origin: LatLng,
    duration_min: int,
    router: ViaRouter,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], float] | None = None,
    interval_s: float = REQUEST_INTERVAL_S,
    max_total_s: float = MAX_TOTAL_S,
    bearing_count: int = len(BEARINGS) + len(EXTRA_BEARINGS),
    radius_scales: tuple[float, ...] = (1.0,),
    spreads: tuple[int, ...] = (SPREAD_DEG,),
    max_requests: int = MAX_REQUESTS,
    max_results: int = MAX_RESULTS,
) -> GenerationResult:
    """원하는 시간(분)에 맞는 순환 경로 후보를 만든다. 서버가 계속 응답하지 않으면 RouteGenerationError.

    기본값은 공용 서버용이다(방위 8개, 요청 11회). 직접 띄운 서버라면 방위 수, 반경 배율, 벌어짐 각도 조합과 요청 상한을
    늘려 더 많은 모양을 시도할 수 있다. 시도한 모양을 모두 본 뒤 겹치지 않는 후보를 max_results개까지 고른다.
    """
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    if not MIN_MINUTES <= duration_min <= MAX_MINUTES:
        raise ValueError(f"산책 시간은 {MIN_MINUTES}~{MAX_MINUTES}분이어야 해요")
    target_m = duration_min * WALK_METERS_PER_MIN
    base_radius = target_m / 4
    plan = search_plan(bearing_count, radius_scales, spreads)[:max_requests]

    started = clock()
    requests = 0
    failures = 0
    last_start: float | None = None
    candidates: list[GeneratedRoute] = []

    def attempt(bearing: int, radius_m: float, spread: int) -> None:
        nonlocal requests, failures, last_start
        if last_start is not None:
            wait = interval_s - (clock() - last_start)
            if wait > 0:
                sleep(wait)
        last_start = clock()
        requests += 1
        try:
            path = router.route_via(waypoints(origin, radius_m, bearing, spread))
        except RoutingUnavailable as exc:
            failures += 1
            logger.warning("경로 생성 요청 실패: %s", exc)
            return
        failures = 0
        if len(path.points) < 2:
            return
        candidates.append(evaluate(path, target_m, bearing, radius_m, spread))

    def can_continue() -> bool:
        return failures < MAX_FAILURES and requests < max_requests and clock() - started <= max_total_s

    def select() -> list[GeneratedRoute]:
        chosen: list[GeneratedRoute] = []
        chosen_edges: list[dict[EdgeKey, float]] = []
        for candidate in sorted((c for c in candidates if c.passes), key=lambda c: c.score):
            edges = edge_lengths(candidate.points)
            if all(_shared_ratio(edges, other) <= MAX_CANDIDATE_OVERLAP for other in chosen_edges):
                chosen.append(candidate)
                chosen_edges.append(edges)
            if len(chosen) == max_results:
                break
        return chosen

    # 앞의 네 모양(동서남북)만 먼저 시도해 서버가 전혀 안 되면 더 두드리지 않고 멈춘다.
    first = [shape for shape in plan if shape[0] % 90 == 0 and shape[1:] == plan[0][1:]][:4]
    for bearing, scale, spread in first:
        if not can_continue():
            break
        attempt(bearing, base_radius * scale, spread)
    if not candidates:
        raise RouteGenerationError("길찾기 서버에서 경로를 받지 못했어요.")

    # 나머지 모양도 모두 본 뒤 좋은 후보를 고른다. 먼저 몇 개가 모였다고 멈추면 뒤의 더 좋은 후보를 놓친다.
    # 대신 요청이 항상 계획한 수만큼 나가므로, 공용 서버를 쓰는 동안은 계정당 대기 시간과 동시 1건 제한으로 부하를 막는다.
    for bearing, scale, spread in plan:
        if (bearing, scale, spread) in first:
            continue
        if not can_continue():
            break
        attempt(bearing, base_radius * scale, spread)
    selected = select()
    if len(selected) < max_results:
        # 시간 오차가 큰 후보는 반경을 고쳐 다시 시도한다. 후보마다 한 번만 하고, 성공할 때까지 반복하지 않는다.
        for base in sorted(candidates, key=lambda c: c.score)[:MAX_CORRECTIONS]:
            if base.error_pct / 100 <= CORRECT_ABOVE or not can_continue():
                continue
            # 거리가 0에 가깝거나 크게 틀려도 반경이 폭주하지 않게 배율을 제한한다.
            scale = target_m / base.distance_m if base.distance_m > 0 else 2.0
            attempt(base.bearing, base.radius_m * min(MAX_CORRECTION, max(1 / MAX_CORRECTION, scale)), base.spread_deg)
        selected = select()
    rejected = None if selected else min(candidates, key=lambda c: c.score)
    return GenerationResult(candidates=selected, requests=requests, best_rejected=rejected)


class GenerationBusy(Exception):
    """다른 생성이 진행 중이거나 이 사용자가 방금 생성했다. retry_after_s 뒤에 다시 시도할 수 있다."""

    def __init__(self, message: str, retry_after_s: int):
        super().__init__(message)
        self.retry_after_s = retry_after_s


class GenerationGate:
    """공용 길찾기 서버를 아끼기 위한 입구. 프로세스 안에서 동시에 한 건만 처리하고, 사용자마다 끝난 뒤 잠깐 쉬게 한다.

    프로세스 단위라서 워커가 여러 개면 전역이 아니다. 시연·소규모 운영(워커 1개)을 전제로 한다.
    """

    def __init__(self, cooldown_s: float = 10.0, busy_retry_s: int = 5, clock: Callable[[], float] = time.monotonic):
        self.cooldown_s = cooldown_s
        self.busy_retry_s = busy_retry_s
        self.clock = clock
        self._mutex = threading.Lock()
        self._busy = False
        self._finished: dict[int, float] = {}

    def acquire(self, user_id: int) -> None:
        with self._mutex:
            if self._busy:
                raise GenerationBusy("다른 경로를 만드는 중이에요. 잠시 뒤에 다시 시도해 주세요.", self.busy_retry_s)
            finished = self._finished.get(user_id)
            if finished is not None:
                remaining = self.cooldown_s - (self.clock() - finished)
                if remaining > 0:
                    raise GenerationBusy("방금 경로를 만들었어요. 잠시 뒤에 다시 시도해 주세요.", math.ceil(remaining))
            self._busy = True

    def release(self, user_id: int, rest: bool = True) -> None:
        """끝났음을 알린다. 서버 장애로 실패했으면 rest=False로 쉬는 시간 없이 바로 다시 시도하게 한다."""
        with self._mutex:
            now = self.clock()
            self._busy = False
            if rest:
                self._finished[user_id] = now
            # 쉬는 시간이 지난 기록은 지워 사용자 수만큼 계속 늘지 않게 한다.
            self._finished = {uid: t for uid, t in self._finished.items() if now - t < self.cooldown_s}


gate = GenerationGate()
