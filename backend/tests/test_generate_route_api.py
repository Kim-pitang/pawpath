import json
from pathlib import Path

import pytest

from app import api
from app.main import app
from app.services import route_generator as rg
from app.services.routing_service import RoutedPath, RoutingUnavailable

SAMPLES = {s["key"]: s for s in json.loads((Path(__file__).parent / "fixtures" / "route_generator" / "osrm_samples.json").read_text())}
BODY = {"latitude": 37.555869, "longitude": 126.9105, "duration_min": 30}


def path_of(key: str) -> RoutedPath:
    sample = SAMPLES[key]
    return RoutedPath(
        points=[[lat, lng] for lng, lat in sample["coordinates"]],
        distance_m=sample["distance"],
        snap_distances_m=tuple(sample["snaps"]),
    )


class FakeViaRouter:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def route_via(self, points):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def generate(client, monkeypatch):
    """가짜 라우터와 새 게이트로 바꿔 끼우고, 대기 시간 없이 돌린다."""
    monkeypatch.setattr(rg.time, "sleep", lambda seconds: None)
    holder = {}

    def install(result, gate=None):
        router = FakeViaRouter(result)
        holder["router"] = router
        app.dependency_overrides[api.generation_router] = lambda: router
        app.dependency_overrides[api.generation_gate] = lambda: gate or rg.GenerationGate(cooldown_s=0)
        return router

    yield client, install
    app.dependency_overrides.pop(api.generation_router, None)
    app.dependency_overrides.pop(api.generation_gate, None)


def test_returns_candidates_with_route_and_metrics(generate):
    client, install = generate
    router = install(path_of("mangwon-30-0"))
    response = client.post("/api/routes/generate", json=BODY)
    assert response.status_code == 200
    data = response.json()
    assert data["target_min"] == 30 and data["notice"] is None
    assert 1 <= len(data["candidates"]) <= 3
    first = data["candidates"][0]
    assert len(first["route"]) > 10
    assert rg.haversine_m(tuple(first["route"][0]), tuple(first["route"][-1])) <= rg.MAX_CLOSURE_M
    assert first["repeated_pct"] <= 25
    assert router.calls == 8  # 가짜 라우터가 같은 경로만 돌려줘 후보가 모자라 추가 방위까지 찾는다


def test_no_passing_candidate_returns_empty_list_with_a_notice(generate):
    client, install = generate
    install(path_of("hangang-10-0"))
    data = client.post("/api/routes/generate", json={**BODY, "duration_min": 20}).json()
    assert data["candidates"] == []
    assert "찾지 못했어요" in data["notice"]


def test_router_failure_is_a_502_without_leaking_coordinates(generate, caplog):
    client, install = generate
    install(RoutingUnavailable("ConnectError"))
    with caplog.at_level("DEBUG"):
        response = client.post("/api/routes/generate", json=BODY)
    assert response.status_code == 502
    for leaked in ("37.5558", "126.9105"):
        assert leaked not in response.text
        assert leaked not in caplog.text


def test_a_server_failure_does_not_make_the_user_wait_before_retrying(generate):
    client, install = generate
    gate = rg.GenerationGate(cooldown_s=10)
    install(RoutingUnavailable("ConnectError"), gate)
    assert client.post("/api/routes/generate", json=BODY).status_code == 502
    install(path_of("mangwon-30-0"), gate)
    assert client.post("/api/routes/generate", json=BODY).status_code == 200


def test_routing_disabled_is_a_503(client):
    # 테스트 환경은 ROUTING_PROVIDER=none이라 기본 의존성이 None을 돌려준다.
    assert client.post("/api/routes/generate", json=BODY).status_code == 503


@pytest.mark.parametrize(
    "changes",
    [
        {"duration_min": 19},
        {"duration_min": 91},
        {"latitude": 91},
        {"longitude": -181},
        {"latitude": "NaN"},
        {"longitude": "Infinity"},
    ],
)
def test_invalid_input_is_rejected(generate, changes):
    client, install = generate
    router = install(path_of("mangwon-30-0"))
    assert client.post("/api/routes/generate", json={**BODY, **changes}).status_code == 422
    assert router.calls == 0


def test_a_busy_gate_returns_429_with_retry_after(generate):
    client, install = generate
    gate = rg.GenerationGate(cooldown_s=0)
    gate.acquire(999)  # 다른 사용자가 생성하는 중
    router = install(path_of("mangwon-30-0"), gate)
    response = client.post("/api/routes/generate", json=BODY)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "5"
    assert router.calls == 0


def test_the_same_user_must_wait_between_generations(generate):
    client, install = generate
    install(path_of("mangwon-30-0"), rg.GenerationGate(cooldown_s=10))
    assert client.post("/api/routes/generate", json=BODY).status_code == 200
    second = client.post("/api/routes/generate", json=BODY)
    assert second.status_code == 429
    assert 1 <= int(second.headers["retry-after"]) <= 10


def test_gate_is_released_even_when_generation_fails(generate):
    client, install = generate
    gate = rg.GenerationGate(cooldown_s=0)
    install(RoutingUnavailable("ConnectError"), gate)
    assert client.post("/api/routes/generate", json=BODY).status_code == 502
    assert gate._busy is False
    install(path_of("mangwon-30-0"), gate)
    assert client.post("/api/routes/generate", json=BODY).status_code == 200


def test_gate_cooldown_expires_and_old_entries_are_pruned():
    now = [0.0]
    gate = rg.GenerationGate(cooldown_s=10, clock=lambda: now[0])
    gate.acquire(1)
    gate.release(1)
    with pytest.raises(rg.GenerationBusy):
        gate.acquire(1)
    now[0] = 11
    gate.acquire(2)
    gate.release(2)
    assert 1 not in gate._finished
    gate.acquire(1)  # 쉬는 시간이 지나 다시 가능


def test_login_is_required_when_auth_is_required(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    try:
        router = FakeViaRouter(path_of("mangwon-30-0"))
        app.dependency_overrides[api.generation_router] = lambda: router
        response = client.post("/api/routes/generate", json=BODY)
        assert response.status_code == 401
        assert router.calls == 0
    finally:
        app.dependency_overrides.pop(api.generation_router, None)
        get_settings.cache_clear()


def test_limits_come_from_settings_so_a_self_hosted_server_can_relax_them(client, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("ROUTING_MIN_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("GENERATION_COOLDOWN_SECONDS", "0")
    monkeypatch.setenv("GENERATION_MAX_SECONDS", "12")
    get_settings.cache_clear()
    sleeps = []
    monkeypatch.setattr(rg.time, "sleep", lambda seconds: sleeps.append(seconds))
    gate = rg.GenerationGate(cooldown_s=10)
    monkeypatch.setattr(rg, "gate", gate)
    router = FakeViaRouter(path_of("mangwon-30-0"))
    app.dependency_overrides[api.generation_router] = lambda: router
    try:
        assert client.post("/api/routes/generate", json=BODY).status_code == 200
        assert client.post("/api/routes/generate", json=BODY).status_code == 200  # 대기 시간 0이라 바로 다시 가능
        assert sleeps == []
        assert gate.cooldown_s == 0
    finally:
        app.dependency_overrides.pop(api.generation_router, None)
        get_settings.cache_clear()


def test_defaults_match_the_public_server_policy():
    from app.config import Settings

    settings = Settings()
    assert settings.routing_min_interval_seconds >= 1.0
    assert settings.generation_max_seconds == 30.0
    assert settings.generation_cooldown_seconds == 10.0
