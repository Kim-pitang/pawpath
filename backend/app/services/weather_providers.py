"""날씨 제공자. 새 API는 WeatherProvider 프로토콜만 구현하면 교체할 수 있다."""
import math
from datetime import datetime, timedelta
from typing import Protocol

import httpx

from app.recommender.types import HourWeather

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_FIELDS = (
    "temperature_2m,apparent_temperature,precipitation_probability,precipitation,"
    "relative_humidity_2m,wind_speed_10m,uv_index,is_day"
)
FORECAST_HOURS = 48
SCENARIOS = ("rain_later", "heatwave", "cold", "heavy_rain")


class WeatherUnavailable(Exception):
    """제공자에서 날씨를 가져오지 못했다."""


class WeatherProvider(Protocol):
    name: str

    def fetch(self, latitude: float, longitude: float, now: datetime) -> list[HourWeather]:
        """지금 시각을 포함한 시간별 예보를 돌려준다. 실패하면 WeatherUnavailable을 던진다."""
        ...


class OpenMeteoProvider:
    name = "open-meteo"

    def __init__(self, timezone: str, timeout_seconds: float, client: httpx.Client | None = None):
        self.timezone = timezone
        self.timeout_seconds = timeout_seconds
        self.client = client

    def fetch(self, latitude: float, longitude: float, now: datetime) -> list[HourWeather]:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": HOURLY_FIELDS,
            "wind_speed_unit": "ms",
            "timezone": self.timezone,
            "forecast_days": 3,
        }
        try:
            client = self.client or httpx.Client(timeout=self.timeout_seconds)
            response = client.get(OPEN_METEO_URL, params=params)
            response.raise_for_status()
            return self._parse(response.json(), now)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise WeatherUnavailable(str(exc)) from exc

    @staticmethod
    def _parse(payload: dict, now: datetime) -> list[HourWeather]:
        hourly = payload["hourly"]
        current_hour = now.replace(minute=0)
        rows = []
        for index, raw_time in enumerate(hourly["time"]):
            time = datetime.fromisoformat(raw_time)
            if time < current_hour:
                continue
            rows.append(
                HourWeather(
                    time=time,
                    temperature=hourly["temperature_2m"][index],
                    apparent_temperature=hourly["apparent_temperature"][index],
                    precipitation_probability=hourly["precipitation_probability"][index] or 0.0,
                    precipitation_mm=hourly["precipitation"][index] or 0.0,
                    humidity=hourly["relative_humidity_2m"][index],
                    wind_speed=hourly["wind_speed_10m"][index],
                    uv_index=hourly["uv_index"][index],
                    is_day=bool(hourly["is_day"][index]),
                )
            )
        if not rows:
            raise ValueError("예보 데이터가 비어 있습니다")
        return rows


def _diurnal(hour: int, mean: float, amplitude: float) -> float:
    """오후 3시에 가장 높은 하루 기온 곡선."""
    return mean + amplitude * math.cos((hour - 15) / 24 * 2 * math.pi)


def _is_daytime(hour: int) -> bool:
    return 7 <= hour < 18


def _hour(time: datetime, mean: float, amplitude: float, prob: float, mm: float, humidity: float, wind: float, uv_peak: float) -> HourWeather:
    temperature = round(_diurnal(time.hour, mean, amplitude), 1)
    daytime = _is_daytime(time.hour)
    uv = round(max(0.0, uv_peak * math.sin((time.hour - 6) / 12 * math.pi)), 1) if daytime else 0.0
    return HourWeather(
        time=time,
        temperature=temperature,
        apparent_temperature=round(temperature - 0.4 * wind + (2.0 if temperature >= 27 and humidity > 60 else 0.0), 1),
        precipitation_probability=prob,
        precipitation_mm=mm,
        humidity=humidity,
        wind_speed=wind,
        uv_index=uv,
        is_day=daytime,
    )


class MockWeatherProvider:
    """외부 API 없이 동작하는 온화한 날씨. WEATHER_PROVIDER=mock이거나 API 실패 시 쓴다."""

    name = "mock"

    def fetch(self, latitude: float, longitude: float, now: datetime) -> list[HourWeather]:
        first = now.replace(minute=0)
        return [_hour(first + timedelta(hours=i), 17, 5, 10, 0.0, 55, 2.5, 4) for i in range(FORECAST_HOURS)]


def scenario_forecast(scenario: str, now: datetime, anchor: datetime) -> list[HourWeather]:
    """시연용 날씨 시나리오. anchor는 보호자의 다음 가능 시간 첫 출발 시각이다.

    화면에 항상 '시연용'으로 표시하며, 실제 날씨로 표시하지 않는다.
    """
    first = now.replace(minute=0)
    rows = []
    for offset in range(FORECAST_HOURS):
        time = first + timedelta(hours=offset)
        if scenario == "rain_later":
            # 첫 출발 1시간 뒤부터 예보 끝까지 비가 내려, 어느 시각에 시연해도 첫 출발만 비를 피한다.
            raining = time >= anchor + timedelta(hours=1)
            prob = 85.0 if raining else 20.0
            mm = 1.5 if raining else 0.0
            rows.append(_hour(time, 18, 4, prob, mm, 80 if raining else 60, 3.0, 3))
        elif scenario == "heatwave":
            rows.append(_hour(time, 29, 5, 10, 0.0, 70, 1.5, 10))
        elif scenario == "cold":
            rows.append(_hour(time, -3, 4, 10, 0.0, 45, 4.0, 2))
        elif scenario == "heavy_rain":
            rows.append(_hour(time, 19, 2, 95, 6.0, 92, 6.0, 1))
        else:
            raise ValueError(f"알 수 없는 시나리오: {scenario}")
    return rows
