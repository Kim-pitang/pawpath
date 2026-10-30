from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import httpx
import pytest

from app.config import Settings
from app.database import Base, SessionLocal, engine
from app.models import WeatherRecord
from app.recommender.types import TimeWindow
from app.services.weather_providers import (
    MockWeatherProvider,
    OpenMeteoProvider,
    WeatherUnavailable,
    scenario_forecast,
)
from app.services.weather_service import get_weather

NOW = datetime(2026, 10, 30, 10, 20)
WINDOWS = (TimeWindow(16, 20),)
SETTINGS = Settings(weather_provider="open-meteo", weather_cache_minutes=30)


def open_meteo_payload() -> dict:
    times = [(NOW.replace(hour=0, minute=0) + timedelta(hours=i)).isoformat(timespec="minutes") for i in range(72)]
    return {
        "hourly": {
            "time": times,
            "temperature_2m": [15.0] * 72,
            "apparent_temperature": [14.0] * 72,
            "precipitation_probability": [20] * 72,
            "precipitation": [0.0] * 72,
            "relative_humidity_2m": [50] * 72,
            "wind_speed_10m": [2.0] * 72,
            "uv_index": [3.0] * 72,
            "is_day": [1] * 72,
        }
    }


def provider_with(handler) -> OpenMeteoProvider:
    return OpenMeteoProvider("Asia/Seoul", 1.0, client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.fixture
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        yield session


def test_open_meteo_parses_hours_from_now_and_requests_metric_wind():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json=open_meteo_payload())

    hours = provider_with(handler).fetch(37.5, 126.9, NOW)
    assert hours[0].time == NOW.replace(minute=0)
    assert hours[0].apparent_temperature == 14.0
    assert hours[0].is_day is True
    assert seen["wind_speed_unit"] == "ms"
    assert seen["timezone"] == "Asia/Seoul"
    assert "uv_index" in seen["hourly"]


def test_open_meteo_treats_missing_probability_as_zero():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = open_meteo_payload()
        payload["hourly"]["precipitation_probability"] = [None] * 72
        return httpx.Response(200, json=payload)

    assert provider_with(handler).fetch(37.5, 126.9, NOW)[0].precipitation_probability == 0.0


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(500),
        lambda request: httpx.Response(200, json={"unexpected": True}),
        lambda request: (_ for _ in ()).throw(httpx.ConnectTimeout("timeout")),
    ],
)
def test_open_meteo_failures_raise_weather_unavailable(handler):
    with pytest.raises(WeatherUnavailable):
        provider_with(handler).fetch(37.5, 126.9, NOW)


def test_service_falls_back_to_mock_when_the_api_fails(db):
    result = get_weather(db, NOW, WINDOWS, provider=provider_with(lambda r: httpx.Response(503)), settings=SETTINGS)
    assert result.is_mock is True
    assert result.source == "mock-fallback"
    assert result.notice is not None
    assert len(result.hours) >= 24


def test_service_stores_and_reuses_real_weather(db):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json=open_meteo_payload())

    provider = provider_with(handler)
    first = get_weather(db, NOW, WINDOWS, provider=provider, settings=SETTINGS)
    second = get_weather(db, NOW + timedelta(minutes=10), WINDOWS, provider=provider, settings=SETTINGS)
    assert first.is_mock is False and second.is_mock is False
    assert calls["count"] == 1
    assert db.query(WeatherRecord).filter_by(source="open-meteo").count() > 24


def test_service_refetches_after_the_cache_expires(db):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json=open_meteo_payload())

    provider = provider_with(handler)
    get_weather(db, NOW, WINDOWS, provider=provider, settings=SETTINGS)
    get_weather(db, NOW + timedelta(minutes=45), WINDOWS, provider=provider, settings=SETTINGS)
    assert calls["count"] == 2


def test_concurrent_requests_do_not_collide(db):
    """홈 화면이 날씨를 동시에 요청해도 500 오류가 나지 않아야 한다."""
    calls = {"count": 0}
    workers = 8
    barrier = Barrier(workers)

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json=open_meteo_payload())

    provider = provider_with(handler)

    def load(_):
        with SessionLocal() as session:
            barrier.wait()
            return get_weather(session, NOW, WINDOWS, provider=provider, settings=SETTINGS).source

    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(load, range(workers)))

    assert results == ["open-meteo"] * workers
    assert calls["count"] == 1


def test_scenario_is_labeled_as_a_demo_and_never_as_real_weather(db):
    result = get_weather(db, NOW, WINDOWS, scenario="rain_later", settings=SETTINGS)
    assert result.is_mock is True
    assert "시연용" in result.notice
    assert result.source == "scenario:rain_later"


def test_unknown_scenario_is_rejected(db):
    with pytest.raises(ValueError):
        get_weather(db, NOW, WINDOWS, scenario="meteor", settings=SETTINGS)


def test_rain_scenario_starts_one_hour_after_the_anchor():
    anchor = NOW.replace(hour=16, minute=0)
    rows = {row.time: row for row in scenario_forecast("rain_later", NOW, anchor)}
    assert rows[anchor].precipitation_mm == 0
    assert rows[anchor + timedelta(hours=1)].precipitation_mm > 0


def test_mock_provider_covers_the_next_two_days():
    rows = MockWeatherProvider().fetch(37.5, 126.9, NOW)
    assert rows[0].time == NOW.replace(minute=0)
    assert len(rows) == 48
