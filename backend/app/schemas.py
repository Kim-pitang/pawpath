"""API 요청과 응답 스키마."""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator

Size = Literal["small", "medium", "large"]
Level = Literal["low", "medium", "high"]
Personality = Literal["active", "timid", "curious"]
PathPreference = Literal["familiar", "new"]
NoveltyReaction = Literal["calm", "cautious", "anxious"]
Difficulty = Literal["easy", "just_right", "hard"]
WeatherScenario = Literal["live", "rain_later", "rain_now", "heatwave", "cold", "heavy_rain"]
TimeBucket = Literal["morning", "lunch", "afternoon", "evening"]
TrackingSource = Literal["gps", "manual", "simulation"]


class PetBase(BaseModel):
    name: str = Field(min_length=1, max_length=30)
    breed: str = Field(min_length=1, max_length=50)
    age_years: float = Field(ge=0, le=35)
    weight_kg: float = Field(gt=0, le=120)
    size: Size
    activity_level: Level
    personality: Personality
    path_preference: PathPreference
    heat_sensitivity: Level
    novelty_reaction: NoveltyReaction
    preferred_distance_km: float | None = Field(default=None, gt=0, le=30)
    preferred_time_bucket: TimeBucket | None = None


class PetCreate(PetBase):
    pass


class PetUpdate(PetBase):
    pass


class PetRead(PetBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    feedback_total: int
    created_at: datetime
    updated_at: datetime


class TimeWindowSchema(BaseModel):
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)

    @model_validator(mode="after")
    def _end_after_start(self) -> "TimeWindowSchema":
        if self.end_hour <= self.start_hour:
            raise ValueError("종료 시각은 시작 시각보다 늦어야 합니다")
        return self


class ScheduleSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    available_windows: list[TimeWindowSchema] = Field(min_length=1, max_length=6)
    preferred_duration_min: int = Field(ge=10, le=180)
    walks_per_day: int = Field(ge=1, le=4)


class WeatherHour(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    time: datetime
    temperature: float
    apparent_temperature: float
    precipitation_probability: float
    precipitation_mm: float
    humidity: float
    wind_speed: float
    uv_index: float | None
    is_day: bool


class WeatherMeta(BaseModel):
    source: str
    scenario: str
    is_mock: bool
    notice: str | None


class CurrentWeather(WeatherMeta):
    current: WeatherHour
    condition: str
    walk_comfort_hint: str


class ForecastWeather(WeatherMeta):
    hours: list[WeatherHour]


class CourseSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str
    area: str
    start_lat: float
    start_lng: float
    distance_km: float
    duration_min: int
    has_park: bool
    park_names: list[str]
    lighting: str
    is_paved: bool
    surface_note: str
    crowd_level: str
    pet_allowed: bool
    pet_rule_note: str
    is_familiar: bool
    shade_level: float
    difficulty: str
    traffic_exposure: str
    scenery_tags: list[str]
    facilities: list[dict]
    data_sources: dict
    environment: dict | None = None
    # 내 산책길로 만든 코스. 주인에게만 보인다.
    is_personal: bool = False


class CourseDetail(CourseSummary):
    route: list[list[float]]


class ApproachRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class ApproachRead(BaseModel):
    mode: Literal["routed", "straight", "too_far"]
    distance_m: float
    duration_min: int
    route: list[list[float]]
    notice: str | None


class WalkingRouteRequest(BaseModel):
    from_latitude: float = Field(ge=-90, le=90)
    from_longitude: float = Field(ge=-180, le=180)
    to_latitude: float = Field(ge=-90, le=90)
    to_longitude: float = Field(ge=-180, le=180)


class AlternativeRequest(BaseModel):
    """위치는 없어도 된다. 없으면 복귀 경로 대신 안내 문구를 돌려준다."""

    pet_id: int
    course_id: int
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    progress_m: float = Field(default=0, ge=0)
    weather_scenario: WeatherScenario = "live"


class RecommendationRequest(BaseModel):
    pet_id: int
    weather_scenario: WeatherScenario = "live"


class WalkCreate(BaseModel):
    pet_id: int
    course_id: int
    recommendation_id: int | None = None
    duration_min: int = Field(ge=1, le=600)
    started_at: datetime | None = None
    tracking_source: TrackingSource = "manual"
    distance_km: float | None = Field(default=None, ge=0, le=100)


class FeedbackBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    walk_rating: int
    pet_rating: int
    difficulty: str
    weather_rating: int
    would_revisit: bool
    memo: str
    affinity_before: float
    affinity_after: float
    created_at: datetime


class WalkRead(BaseModel):
    id: int
    pet_id: int
    course_id: int
    course_name: str
    distance_km: float
    recommendation_id: int | None
    started_at: datetime
    ended_at: datetime
    duration_min: int
    feedback: FeedbackBrief | None
    tracking_source: str = "manual"
    is_simulated: bool = False


class FeedbackCreate(BaseModel):
    walk_id: int
    walk_rating: int = Field(ge=1, le=5)
    pet_rating: int = Field(ge=1, le=5)
    difficulty: Difficulty
    weather_rating: int = Field(ge=1, le=5)
    would_revisit: bool
    memo: str = Field(default="", max_length=500)


class FeedbackRead(FeedbackBrief):
    walk_id: int
    pet_id: int
    course_id: int
    course_name: str
    signal: float


# 나만의 산책길
Visibility = Literal["private", "link", "public"]
WalkSourceType = Literal["recorded", "imported"]
SavedWalkSort = Literal["recent", "distance"]


class WalkPointInput(BaseModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    altitude: float | None = Field(default=None, allow_inf_nan=False)
    recorded_at: datetime | None = None
    accuracy: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    segment: int = Field(default=0, ge=0)


class SavedWalkCreate(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    pet_id: int | None = None
    memo: str = Field(default="", max_length=1000)
    visibility: Visibility = "private"
    share_memo: bool = False
    source_type: WalkSourceType = "recorded"
    client_id: str | None = Field(default=None, min_length=8, max_length=64)
    # 기록 화면의 타이머 값. 일시정지를 뺀 시간이라 GPS 시각 차이보다 정확하다.
    duration_sec: int | None = Field(default=None, ge=0, le=7 * 24 * 3600)
    points: list[WalkPointInput] = Field(min_length=2, max_length=100_000)


class SavedWalkUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=80)
    pet_id: int | None = None
    memo: str | None = Field(default=None, max_length=1000)
    visibility: Visibility | None = None
    share_memo: bool | None = None


class SavedWalkSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pet_id: int | None
    pet_name: str | None = None
    title: str
    source_type: WalkSourceType
    started_at: datetime
    ended_at: datetime | None
    distance_m: float
    duration_sec: int | None
    average_speed_mps: float | None
    has_timestamps: bool
    point_count: int
    visibility: Visibility
    preview: list[list[list[float]]]


class PhotoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content_type: str
    size_bytes: int
    created_at: datetime


class PersonalCourseRead(BaseModel):
    """산책길을 추천 후보로 등록한 상태."""

    id: int
    active: bool
    area: str
    in_current_area: bool
    environment_measured: bool
    # 주변 환경 측정: pending(측정 중), done, failed, off(서버에서 꺼 둠)
    measurement: Literal["pending", "done", "failed", "off"]
    unknown: list[str]
    notes: list[str]


class SavedWalkDetail(SavedWalkSummary):
    course: PersonalCourseRead | None = None
    memo: str
    share_token: str | None
    share_expires_at: datetime | None
    share_memo: bool
    route: list[list[list[float]]]
    photos: list[PhotoRead] = []


class ShareRequest(BaseModel):
    expires_in_days: int | None = Field(default=None, ge=1, le=365)
    share_memo: bool = False


class SharedWalkRead(BaseModel):
    """공유 링크로 보는 값. 시각, 정확도, 반려동물, 보호자 정보를 담지 않는다."""

    title: str
    distance_m: float
    duration_sec: int | None
    memo: str | None
    start: list[float]
    end: list[float]
    route: list[list[list[float]]]


class PublicWalkSummary(BaseModel):
    token: str
    title: str
    distance_m: float
    duration_sec: int | None
    preview: list[list[list[float]]]


class GpxPointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    segment: int
    latitude: float
    longitude: float
    altitude: float | None
    recorded_at: datetime | None


class DuplicateWalk(BaseModel):
    id: int
    title: str


class GpxPreview(BaseModel):
    name: str | None
    version: str
    track_count: int
    segment_count: int
    point_count: int
    invalid_point_count: int
    has_timestamps: bool
    distance_m: float
    duration_sec: int | None
    started_at: datetime | None
    ended_at: datetime | None
    average_speed_mps: float | None
    warnings: list[str]
    duplicate_of: DuplicateWalk | None
    points: list[GpxPointRead]


# 계정
def _normalize_login_id(value: object) -> object:
    """형식을 검사하기 전에 공백을 지우고 소문자로 바꾼다. Alice와 alice는 같은 아이디다."""
    return value.strip().lower() if isinstance(value, str) else value


LoginId = Annotated[str, BeforeValidator(_normalize_login_id), StringConstraints(min_length=3, max_length=30, pattern=r"^[a-z0-9][a-z0-9_.-]*$")]


class SignupRequest(BaseModel):
    login_id: LoginId
    password: str = Field(min_length=8, max_length=128)
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]


class LoginRequest(BaseModel):
    login_id: Annotated[str, BeforeValidator(_normalize_login_id), StringConstraints(min_length=1, max_length=30)]
    password: str = Field(min_length=1, max_length=128)


class AccountUser(BaseModel):
    id: int
    name: str
    # Google 로그인 사용자는 아이디가 없다.
    login_id: str | None
    email: str | None = None
    provider: Literal["password", "google"]


class AccountRead(BaseModel):
    authenticated: bool
    auth_required: bool
    google_enabled: bool
    user: AccountUser | None

