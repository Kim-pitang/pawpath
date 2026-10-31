"""환경변수 기반 설정. 민감정보와 환경별 값은 .env에서만 관리한다."""
from functools import lru_cache
from typing import NamedTuple

from pydantic import Field, model_validator
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
    # 산책길 자동 생성이 길찾기 서버를 부르는 방식. 기본값은 공용 서버(초당 1회 안내) 기준이다.
    # 자체 OSRM 서버를 쓰면 간격을 0으로, 계정당 대기를 줄여도 된다.
    routing_min_interval_seconds: float = 1.1
    generation_max_seconds: float = 30.0
    generation_cooldown_seconds: float = 10.0
    # 어떤 모양을 얼마나 시도할지. 기본값(방위 8개, 요청 11회)은 공용 서버용이고, 자체 서버에서는 늘릴 수 있다.
    # 시도 수 = 방위 수 × 반경 배율 수 × 벌어짐 각도 수(요청 상한까지), 후보가 모자라면 보정 요청이 몇 번 더 나간다.
    generation_bearings: int = Field(default=8, ge=4, le=72)
    generation_radius_scales: str = "1.0"  # 쉼표로 구분. 첫 값이 기본 모양
    generation_spreads: str = "30"  # 경유점 두 개가 방위 양옆으로 벌어지는 각도(도), 쉼표로 구분. 첫 값이 기본 모양
    generation_max_requests: int = Field(default=11, ge=4, le=300)
    generation_pool_size: int = Field(default=5, ge=1, le=50)  # 평가 전에 남기는 서로 다른 후보 수
    generation_max_results: int = Field(default=5, ge=1, le=10)  # 화면에 돌려주는 후보 수

    # 내 산책길을 추천 후보로 등록할 때 경로 주변 환경을 OSM에서 측정한다: overpass 또는 none(측정하지 않음)
    environment_provider: str = "overpass"

    # 추천 가중치 JSON. 비워 두면 기본값. 예: {"pet_fit": 0.3, "feedback": 0.1}
    recommender_weights: str = ""
    # 추천 알고리즘 버전: v2(안전 단계 + 5개 묶음) 또는 v1(이전 6항목 가중합)
    recommender_version: str = "v2"

    # 추천 이유 문장 생성: none(템플릿만) 또는 ollama
    llm_provider: str = "none"
    llm_base_url: str = "http://localhost:11434"
    llm_model: str = "gemma4:e4b"
    llm_timeout_seconds: float = 60.0

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    seed_demo_pet: bool = True
    # 참이면 로그인해야 앱을 쓸 수 있다. 거짓이면 로그인하지 않은 사용자는 시연 보호자로 동작한다.
    auth_required: bool = False

    # Google 로그인(선택). Google Cloud 콘솔에서 만든 OAuth 클라이언트 값. 둘 다 있어야 켜진다. 비밀값은 .env에만 둔다.
    google_client_id: str = ""
    google_client_secret: str = ""
    # 콘솔에 등록한 "승인된 리디렉션 URI"와 글자 하나까지 같아야 한다.
    google_redirect_uri: str = "http://localhost:5173/api/auth/google/callback"

    # 자동 백업. SQLite일 때 서버가 스스로 돌린다. 정책과 복구 방법은 docs/BACKUP.md에 있다.
    backup_enabled: bool = True
    # DB 사본과 탈퇴 기록이 들어간다. DB와 다른 디스크를 권장한다.
    backup_dir: str = "./backups"
    backup_interval_hours: int = Field(default=24, ge=1)
    # 이 기간이 지난 백업을 지운다. 탈퇴한 보호자의 데이터가 백업에 남는 최대 기간이기도 하다.
    backup_retention_days: int = Field(default=14, ge=1)

    @model_validator(mode="after")
    def apply_service_area(self) -> "Settings":
        area = SERVICE_AREAS.get(self.service_area)
        if area is None:
            raise ValueError(f"SERVICE_AREA는 {', '.join(SERVICE_AREAS)} 중 하나여야 해요: {self.service_area}")
        if self.service_latitude is None:
            self.service_latitude = area.latitude
        if self.service_longitude is None:
            self.service_longitude = area.longitude
        self.generation_radius_scale_list  # 잘못된 값이면 서버가 뜰 때 알린다
        self.generation_spread_list
        return self

    @staticmethod
    def _numbers(raw: str, name: str, low: float, high: float) -> tuple[float, ...]:
        try:
            values = tuple(float(part) for part in raw.split(",") if part.strip())
        except ValueError:
            raise ValueError(f"{name}는 쉼표로 구분한 숫자여야 해요: {raw}") from None
        if not values or any(not low <= value <= high for value in values) or len(set(values)) != len(values):
            raise ValueError(f"{name}는 {low}~{high} 사이의 서로 다른 숫자여야 해요: {raw}")
        return values

    @property
    def generation_radius_scale_list(self) -> tuple[float, ...]:
        return self._numbers(self.generation_radius_scales, "GENERATION_RADIUS_SCALES", 0.5, 1.5)

    @property
    def generation_spread_list(self) -> tuple[int, ...]:
        return tuple(round(v) for v in self._numbers(self.generation_spreads, "GENERATION_SPREADS", 10, 60))

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def service_area_label(self) -> str:
        return SERVICE_AREAS[self.service_area].label

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
