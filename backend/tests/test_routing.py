import logging

import httpx
import pytest

from app.config import Settings
from app.services.routing_service import (
    ROUTING_DISABLED_NOTICE,
    ROUTING_FAILED_NOTICE,
    OsrmFootRouter,
    RoutingUnavailable,
    haversine_m,
    plan_approach,
)

ORIGIN = (37.5560, 126.9105)
DESTINATION = (37.5545, 126.9065)
ENABLED = Settings(routing_provider="osrm", routing_max_distance_km=3)
DISABLED = Settings(routing_provider="none", routing_max_distance_km=3)


def osrm_payload() -> dict:
    return {
        "code": "Ok",
        "routes": [
            {
                "distance": 512.3,
                "geometry": {"coordinates": [[126.9105, 37.5560], [126.9080, 37.5550], [126.9065, 37.5545]]},
            }
        ],
    }


def router_with(handler) -> OsrmFootRouter:
    return OsrmFootRouter("https://example.test/routed-foot/", 1.0, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_haversine_matches_a_known_distance():
    assert haversine_m((37.0, 127.0), (38.0, 127.0)) == pytest.approx(111195, abs=50)


def test_osrm_requests_longitude_first_and_returns_latitude_first():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["geometries"] = request.url.params["geometries"]
        return httpx.Response(200, json=osrm_payload())

    path = router_with(handler).route(ORIGIN, DESTINATION)
    assert seen["path"] == "/routed-foot/route/v1/foot/126.9105,37.556;126.9065,37.5545"
    assert seen["geometries"] == "geojson"
    assert path.points[0] == [37.5560, 126.9105]
    assert path.distance_m == 512.3


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(500),
        lambda request: httpx.Response(200, json={"code": "NoRoute", "routes": []}),
        lambda request: httpx.Response(200, json={"unexpected": True}),
        lambda request: (_ for _ in ()).throw(httpx.ConnectTimeout("timeout")),
    ],
)
def test_osrm_failures_raise_routing_unavailable(handler):
    with pytest.raises(RoutingUnavailable):
        router_with(handler).route(ORIGIN, DESTINATION)


def test_plan_uses_the_routed_path_and_walking_pace():
    plan = plan_approach(ORIGIN, DESTINATION, router=router_with(lambda r: httpx.Response(200, json=osrm_payload())), settings=ENABLED)
    assert plan.mode == "routed"
    assert plan.distance_m == 512.3
    assert plan.duration_min == 9
    assert len(plan.route) == 3
    assert plan.notice is None


def test_plan_falls_back_to_a_straight_line_with_a_notice():
    plan = plan_approach(ORIGIN, DESTINATION, router=router_with(lambda r: httpx.Response(503)), settings=ENABLED)
    assert plan.mode == "straight"
    assert plan.route == [list(ORIGIN), list(DESTINATION)]
    assert plan.notice == ROUTING_FAILED_NOTICE


def test_plan_skips_routing_when_disabled():
    plan = plan_approach(ORIGIN, DESTINATION, settings=DISABLED)
    assert plan.mode == "straight"
    assert plan.notice == ROUTING_DISABLED_NOTICE


def test_plan_does_not_call_the_router_when_too_far():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("먼 거리는 외부 길찾기를 호출하면 안 된다")

    far = (37.4979, 127.0276)
    plan = plan_approach(far, DESTINATION, router=router_with(handler), settings=ENABLED)
    assert plan.mode == "too_far"
    assert plan.route == []
    assert plan.distance_m > 3000


def test_failure_logs_do_not_contain_the_user_location(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url}")

    with caplog.at_level(logging.DEBUG):
        plan = plan_approach(ORIGIN, DESTINATION, router=router_with(handler), settings=ENABLED)
    assert plan.mode == "straight"
    assert "37.556" not in caplog.text
    assert "126.9105" not in caplog.text


def test_approach_endpoint_returns_a_plan(client):
    course = client.get("/api/courses").json()[0]
    response = client.post(f"/api/courses/{course['id']}/approach", json={"latitude": course["start_lat"] + 0.001, "longitude": course["start_lng"]})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "straight"
    assert body["route"][-1] == [course["start_lat"], course["start_lng"]]
    assert 100 < body["distance_m"] < 120


def test_approach_endpoint_reports_when_too_far(client):
    course = client.get("/api/courses").json()[0]
    body = client.post(f"/api/courses/{course['id']}/approach", json={"latitude": 35.1796, "longitude": 129.0756}).json()
    assert body["mode"] == "too_far"
    assert body["route"] == []


def test_approach_endpoint_validates_input(client):
    assert client.post("/api/courses/9999/approach", json={"latitude": 37.5, "longitude": 126.9}).status_code == 404
    assert client.post("/api/courses/1/approach", json={"latitude": 95, "longitude": 126.9}).status_code == 422
    assert client.post("/api/courses/1/approach", json={"latitude": 37.5, "longitude": 200}).status_code == 422
    assert client.post("/api/courses/1/approach", json={"latitude": 37.5}).status_code == 422


def test_route_via_sends_all_waypoints_in_one_request_and_returns_snap_distances():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "code": "Ok",
                "routes": [{"distance": 900.0, "geometry": {"coordinates": [[126.9, 37.5], [126.91, 37.51], [126.9, 37.5]]}}],
                "waypoints": [{"distance": 1.5}, {"distance": 20.0}, {"distance": 30.0}, {"distance": 1.5}],
            },
        )

    path = router_with(handler).route_via([(37.5, 126.9), (37.51, 126.91), (37.52, 126.9), (37.5, 126.9)])
    assert len(seen) == 1
    assert seen[0].url.path.count(";") == 3
    assert seen[0].url.params["continue_straight"] == "false"
    assert seen[0].headers["user-agent"].startswith("PawPath/")
    assert path.snap_distances_m == (1.5, 20.0, 30.0, 1.5)
    assert path.points[1] == [37.51, 126.91]


def test_route_via_failure_does_not_leak_coordinates():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with pytest.raises(RoutingUnavailable) as caught:
        router_with(handler).route_via([(37.5, 126.9), (37.51, 126.91)])
    assert "37.5" not in str(caught.value) and "126.9" not in str(caught.value)
