"""환경변수 기반 설정. 민감정보와 환경별 값은 .env에서만 관리한다."""
from functools import lru_cache
from typing import NamedTuple

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceArea(NamedTuple):
    label: str  # 코스 데이터의 area 값과 같다
    latitude: float
    longitude: float


SERVICE_AREAS = {
    "mangwon": ServiceArea("서울 마포구 망원동 일대", 37.5560, 126.9105),
    "gaepo": ServiceArea("서울 강남구 개포동 일대", 37.4883, 127.0652),
}


class Settings(BaseSettings):
    # 값을 비운 항목은 기본값을 쓴다. .env.example을 복사해 일부만 지워도 서버가 뜨게 한다.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore", env_ignore_empty=True)

    database_url: str = "sqlite:///./pawpath.db"

    weather_provider: str = "open-meteo"
    weather_cache_minutes: int = 30
    weather_timeout_seconds: float = 5.0

    # 서비스 지역: 추천과 지도에 쓸 코스를 정한다. mangwon 또는 gaepo
    service_area: str = "mangwon"
    # 날씨를 조회할 좌표. 비워 두면 서비스 지역의 좌표를 쓴다.
    service_latitude: float | None = None
    service_longitude: float | None = None
    service_timezone: str = "Asia/Seoul"

    # 출발점 길찾기, 복귀 경로, 이탈 시 재탐색에 쓰는 도보 길찾기: osrm 또는 none(직선 표시)
    routing_provider: str = "osrm"
    routing_base_url: str = "https://routing.openstreetmap.de/routed-foot"
    routing_timeout_seconds: float = 4.0
    routing_max_distance_km: float = 3.0

    # 추천 가중치 JSON. 비워 두면 기본값. 예: {"weather": 0.3, "safety": 0.2}
    recommender_weights: str = ""

    # 추천 이유 문장 생성: none(템플릿만) 또는 ollama
    llm_provider: str = "none"
    llm_base_url: str = "http://localhost:11434"
    llm_model: str = "gemma4:e4b"
    llm_timeout_seconds: float = 60.0

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    seed_demo_pet: bool = True

    @model_validator(mode="after")
    def apply_service_area(self) -> "Settings":
        area = SERVICE_AREAS.get(self.service_area)
        if area is None:
            raise ValueError(f"SERVICE_AREA는 {', '.join(SERVICE_AREAS)} 중 하나여야 해요: {self.service_area}")
        if self.service_latitude is None:
            self.service_latitude = area.latitude
        if self.service_longitude is None:
            self.service_longitude = area.longitude
        return self

    @property
    def service_area_label(self) -> str:
        return SERVICE_AREAS[self.service_area].label

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
