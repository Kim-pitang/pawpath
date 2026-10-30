"""환경변수 기반 설정. 민감정보와 환경별 값은 .env에서만 관리한다."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str = "sqlite:///./pawpath.db"

    weather_provider: str = "open-meteo"
    weather_cache_minutes: int = 30
    weather_timeout_seconds: float = 5.0

    # 서비스 지역 기본값: 서울 마포구 망원동
    service_latitude: float = 37.5560
    service_longitude: float = 126.9105
    service_timezone: str = "Asia/Seoul"

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    seed_demo_pet: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
