"""날씨 조회 서비스: 실제 API → DB 캐시 → Mock 순으로 동작하고 결과를 기록한다."""
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import WeatherRecord
from app.recommender.timeslots import candidate_starts
from app.recommender.types import HourWeather, TimeWindow
from app.services.weather_providers import (
    SCENARIOS,
    MockWeatherProvider,
    OpenMeteoProvider,
    WeatherProvider,
    WeatherUnavailable,
    scenario_forecast,
)

logger = logging.getLogger(__name__)

# 동시 요청이 같은 예보를 중복 호출하고 같은 행을 넣지 않도록 조회와 저장을 묶는다.
_weather_lock = threading.Lock()

LIVE = "live"
# 날씨 API가 실패해 모의 날씨로 대신한 경우의 출처 이름
MOCK_FALLBACK = "mock-fallback"
SCENARIO_LABELS = {
    "rain_later": "시연용 시나리오: 곧 비가 오는 날",
    "rain_now": "시연용 시나리오: 지금 비가 내리는 상황",
    "heatwave": "시연용 시나리오: 폭염",
    "cold": "시연용 시나리오: 한파",
    "heavy_rain": "시연용 시나리오: 폭우",
}
FALLBACK_NOTICE = "실제 날씨를 가져오지 못해 모의 날씨로 추천했어요."
MOCK_NOTICE = "모의 날씨 데이터를 사용 중이에요."


@dataclass(frozen=True)
class WeatherResult:
    hours: list[HourWeather]
    source: str
    scenario: str
    is_mock: bool
    notice: str | None
    # 예보를 받아 온 시각. 캐시에서 읽었으면 가장 오래된 행의 시각이다.
    fetched_at: datetime | None = None

    def at(self, hour: datetime) -> HourWeather | None:
        return next((row for row in self.hours if row.time == hour), None)


def build_provider(settings: Settings) -> WeatherProvider:
    if settings.weather_provider == "mock":
        return MockWeatherProvider()
    return OpenMeteoProvider(settings.service_timezone, settings.weather_timeout_seconds)


def _to_hour(record: WeatherRecord) -> HourWeather:
    return HourWeather(
        time=record.forecast_time,
        temperature=record.temperature,
        apparent_temperature=record.apparent_temperature,
        precipitation_probability=record.precipitation_probability,
        precipitation_mm=record.precipitation_mm,
        humidity=record.humidity,
        wind_speed=record.wind_speed,
        uv_index=record.uv_index,
        is_day=record.is_day,
    )


def _store(db: Session, source: str, hours: list[HourWeather], now: datetime) -> None:
    existing = {
        record.forecast_time: record
        for record in db.scalars(select(WeatherRecord).where(WeatherRecord.source == source))
    }
    for hour in hours:
        record = existing.get(hour.time)
        if record is None:
            record = WeatherRecord(source=source, forecast_time=hour.time)
            db.add(record)
        record.temperature = hour.temperature
        record.apparent_temperature = hour.apparent_temperature
        record.precipitation_probability = hour.precipitation_probability
        record.precipitation_mm = hour.precipitation_mm
        record.humidity = hour.humidity
        record.wind_speed = hour.wind_speed
        record.uv_index = hour.uv_index
        record.is_day = hour.is_day
        record.fetched_at = now
    try:
        db.commit()
    except IntegrityError:
        # 다른 서버 프로세스가 먼저 저장했다. 추천에는 이미 받은 예보를 그대로 쓴다.
        db.rollback()


def _cached(db: Session, source: str, now: datetime, max_age_minutes: int) -> tuple[list[HourWeather], datetime | None]:
    rows = db.scalars(
        select(WeatherRecord)
        .where(
            WeatherRecord.source == source,
            WeatherRecord.forecast_time >= now.replace(minute=0),
            WeatherRecord.fetched_at >= now - timedelta(minutes=max_age_minutes),
        )
        .order_by(WeatherRecord.forecast_time)
    ).all()
    return [_to_hour(row) for row in rows], min((row.fetched_at for row in rows), default=None)


def _scenario_anchor(now: datetime, windows: tuple[TimeWindow, ...]) -> datetime:
    candidates = candidate_starts(now, windows)
    return candidates[0][0] if candidates else now.replace(minute=0) + timedelta(hours=1)


def get_weather(
    db: Session,
    now: datetime,
    windows: tuple[TimeWindow, ...],
    scenario: str = LIVE,
    provider: WeatherProvider | None = None,
    settings: Settings | None = None,
) -> WeatherResult:
    with _weather_lock:
        return _load_weather(db, now, windows, scenario, provider, settings or get_settings())


def _load_weather(
    db: Session,
    now: datetime,
    windows: tuple[TimeWindow, ...],
    scenario: str,
    provider: WeatherProvider | None,
    settings: Settings,
) -> WeatherResult:
    if scenario != LIVE:
        if scenario not in SCENARIOS:
            raise ValueError(f"알 수 없는 시나리오: {scenario}")
        hours = scenario_forecast(scenario, now, _scenario_anchor(now, windows))
        source = f"scenario:{scenario}"
        _store(db, source, hours, now)
        return WeatherResult(hours, source, scenario, True, SCENARIO_LABELS[scenario], now)

    provider = provider or build_provider(settings)
    if provider.name == "mock":
        hours = provider.fetch(settings.service_latitude, settings.service_longitude, now)
        _store(db, provider.name, hours, now)
        return WeatherResult(hours, provider.name, LIVE, True, MOCK_NOTICE, now)

    cached, fetched_at = _cached(db, provider.name, now, settings.weather_cache_minutes)
    if cached:
        return WeatherResult(cached, provider.name, LIVE, False, None, fetched_at)

    try:
        hours = provider.fetch(settings.service_latitude, settings.service_longitude, now)
    except WeatherUnavailable as exc:
        logger.warning("날씨 API 실패, Mock으로 전환합니다: %s", exc)
        hours = MockWeatherProvider().fetch(settings.service_latitude, settings.service_longitude, now)
        _store(db, MOCK_FALLBACK, hours, now)
        return WeatherResult(hours, MOCK_FALLBACK, LIVE, True, FALLBACK_NOTICE, now)

    _store(db, provider.name, hours, now)
    return WeatherResult(hours, provider.name, LIVE, False, None, now)


def find_record_id(db: Session, source: str, forecast_time: datetime) -> int | None:
    return db.scalar(
        select(WeatherRecord.id).where(WeatherRecord.source == source, WeatherRecord.forecast_time == forecast_time)
    )
