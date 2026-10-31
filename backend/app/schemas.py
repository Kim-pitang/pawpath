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


WalkScope = Literal["profile", "family"]


class ProfileBrief(BaseModel):
    """기록에 붙이는 프로필 정보. 지운 프로필도 이름을 남겨 누구의 기록인지 알 수 있게 한다."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    avatar_key: str
    is_default: bool
    deleted: bool


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


class GenerateRouteRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    duration_min: int = Field(ge=20, le=90)
    # 반려동물을 주면 후보를 그 아이의 성향·날씨·일정에 맞춰 평가하고 순서를 매긴다. 없으면 길이와 시간만 본다.
    pet_id: int | None = None
    weather_scenario: WeatherScenario = "live"


class RouteFitRead(BaseModel):
    """후보가 이 반려동물과 이 시간대에 맞는 정도. 점수는 추천 엔진이 저장된 코스와 같은 기준으로 계산한다."""

    score: float | None
    level: str | None
    summary: str
    details: list[str]
    cautions: list[str]
    highlights: list[str]
    start_label: str | None
    unknown: list[str]
    excluded: list[str]


class GeneratedRouteRead(BaseModel):
    route: list[list[float]]
    distance_m: float
    duration_min: float
    repeated_pct: float
    start_snap_m: float
    fit: RouteFitRead | None = None


class GenerateRouteResponse(BaseModel):
    target_min: int
    candidates: list[GeneratedRouteRead]
    notice: str | None
    scored_for: str | None = None
    fit_notice: str | None = None


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
    # 커뮤니티 산책길로 걸었으면 그 번호. 산책을 마친 뒤 후기로 잇는 데 쓴다.
    community_trail_id: int | None = None
    # 산책을 한 프로필. 프로필을 지워도 누구의 기록인지 남는다.
    profile: ProfileBrief | None = None


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
WalkSourceType = Literal["recorded", "imported", "generated"]
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


class SavedWalkTrailRead(BaseModel):
    """이 산책길을 커뮤니티에 공유한 상태."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    visibility: Literal["public", "private"]


class SavedWalkSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    community_trail: SavedWalkTrailRead | None = None
    id: int
    pet_id: int | None
    pet_name: str | None = None
    # 산책길을 만든 프로필.
    profile: ProfileBrief | None = None
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
    # 지금 프로필이 고치고 지울 수 있으면 참이다. 만든 프로필이나 대표 프로필만 할 수 있다.
    can_manage: bool = True


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


# 산책길 커뮤니티
TrailVisibility = Literal["public", "private"]
TrailSort = Literal["recent", "popular", "rating"]
TrailDifficulty = Literal["easy", "moderate", "hard"]
TrailFeature = Literal["park", "shade", "flat", "paved", "waterside", "forest", "quiet", "lit"]
TrailSuitable = Literal["small", "medium", "large", "senior", "puppy", "active", "timid"]
# 출발점과 도착점을 가리는 반경. 가리지 않는 선택지는 두지 않는다.
HideRadius = Literal[100, 200, 300, 500]


def _clean_text(value: object) -> object:
    """줄바꿈과 탭을 뺀 제어 문자를 지우고 앞뒤 공백을 없앤다. 화면에서는 항상 글자 그대로 표시한다."""
    return "".join(ch for ch in value if ch in "\n\t" or (ch >= " " and ch != "\x7f")).strip() if isinstance(value, str) else value


TrailTitle = Annotated[str, BeforeValidator(_clean_text), StringConstraints(min_length=1, max_length=80)]
TrailDescription = Annotated[str, BeforeValidator(_clean_text), StringConstraints(max_length=2000)]
TrailRegion = Annotated[str, BeforeValidator(_clean_text), StringConstraints(max_length=30)]
ReviewContent = Annotated[str, BeforeValidator(_clean_text), StringConstraints(min_length=1, max_length=1000)]


class TrailPreviewRequest(BaseModel):
    saved_walk_id: int
    hide_radius_m: HideRadius = 200


class TrailPreview(BaseModel):
    saved_walk_id: int
    hide_radius_m: int
    hidden_m: float
    region: str
    distance_m: float
    estimated_min: int
    elevation_gain_m: float | None
    difficulty: TrailDifficulty
    start_label: str | None
    end_label: str | None
    can_navigate: bool
    route: list[list[list[float]]]


class TrailCreate(BaseModel):
    saved_walk_id: int
    title: TrailTitle
    description: TrailDescription = ""
    cover_photo_id: int | None = None
    visibility: TrailVisibility = "public"
    # 비우면 출발점 근처의 서비스 지역 이름을 쓴다.
    region: TrailRegion | None = None
    features: list[TrailFeature] = Field(default_factory=list, max_length=8)
    suitable_for: list[TrailSuitable] = Field(default_factory=list, max_length=7)
    hide_radius_m: HideRadius = 200


class TrailUpdate(BaseModel):
    title: TrailTitle | None = None
    description: TrailDescription | None = None
    cover_photo_id: int | None = None
    visibility: TrailVisibility | None = None
    region: TrailRegion | None = None
    features: list[TrailFeature] | None = Field(default=None, max_length=8)
    suitable_for: list[TrailSuitable] | None = Field(default=None, max_length=7)
    hide_radius_m: HideRadius | None = None


class TrailFilters(BaseModel):
    q: str | None = Field(default=None, max_length=80)
    region: str | None = Field(default=None, max_length=50)
    min_km: float | None = Field(default=None, ge=0, le=1000)
    max_km: float | None = Field(default=None, ge=0, le=1000)
    min_minutes: int | None = Field(default=None, ge=0, le=100_000)
    max_minutes: int | None = Field(default=None, ge=0, le=100_000)
    difficulty: TrailDifficulty | None = None
    suitable: TrailSuitable | None = None
    feature: TrailFeature | None = None
    sort: TrailSort = "recent"


class TrailSummary(BaseModel):
    """카드에 쓰는 공개 값. 원본 산책길의 이름, 메모, 걸은 시각, 공유 토큰, 반려동물 정보는 담지 않는다."""

    id: int
    title: str
    description: str
    region: str
    author_name: str
    cover_photo_id: int | None
    visibility: TrailVisibility
    features: list[str]
    suitable_for: list[str]
    distance_m: float
    estimated_min: int
    elevation_gain_m: float | None
    difficulty: TrailDifficulty
    preview: list[list[list[float]]]
    view_count: int
    like_count: int
    bookmark_count: int
    review_count: int
    average_rating: float | None
    liked: bool
    bookmarked: bool
    is_mine: bool
    created_at: datetime
    updated_at: datetime


class TrailPage(BaseModel):
    items: list[TrailSummary]
    total: int
    page: int
    size: int
    has_next: bool


class TrailReactionPage(TrailPage):
    # 작성자가 비공개로 돌려 지금은 볼 수 없는 산책길 수
    hidden_count: int


class TrailRegionRead(BaseModel):
    region: str
    count: int


class TrailNearbyRequest(BaseModel):
    """위치가 접근 로그에 남지 않도록 본문으로 받는다. 저장하지 않는다."""

    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    radius_km: float = Field(default=5, gt=0, le=50, allow_inf_nan=False)
    limit: int = Field(default=20, ge=1, le=50)


class TrailNearby(TrailSummary):
    distance_from_me_m: float


class TrailRecommended(TrailSummary):
    match_score: int
    reasons: list[str]


class ReviewPhotoRead(BaseModel):
    id: int


class ReviewRead(BaseModel):
    id: int
    trail_id: int
    rating: int
    content: str
    author_name: str
    is_mine: bool
    # 이 산책길의 코스를 GPS로 절반 이상 걸은 기록이 있으면 참이다.
    verified: bool
    edited: bool
    photos: list[ReviewPhotoRead]
    created_at: datetime
    updated_at: datetime


class ReviewPage(BaseModel):
    items: list[ReviewRead]
    total: int
    page: int
    size: int
    has_next: bool


class MyReviewRead(ReviewRead):
    trail_available: bool
    trail_title: str | None


class MyReviewPage(BaseModel):
    items: list[MyReviewRead]
    total: int
    page: int
    size: int
    has_next: bool


class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    content: ReviewContent


class ReviewUpdate(BaseModel):
    rating: int | None = Field(default=None, ge=1, le=5)
    content: ReviewContent | None = None


class TrailOwnerRead(BaseModel):
    saved_walk_id: int
    hide_radius_m: int


class TrailDetail(TrailSummary):
    route: list[list[list[float]]]
    start: list[float]
    end: list[float]
    start_label: str | None
    end_label: str | None
    can_navigate: bool
    my_review: ReviewRead | None
    # 이 산책길을 GPS로 걸은 기록이 있으면 후기에 산책 인증이 붙는다.
    walked: bool
    # 주인에게만 채워진다.
    owner: TrailOwnerRead | None


class LikeState(BaseModel):
    liked: bool
    like_count: int


class BookmarkState(BaseModel):
    bookmarked: bool
    bookmark_count: int


class TrailCourseRead(BaseModel):
    course_id: int


# 계정
def _normalize_login_id(value: object) -> object:
    """형식을 검사하기 전에 공백을 지우고 소문자로 바꾼다. Alice와 alice는 같은 아이디다."""
    return value.strip().lower() if isinstance(value, str) else value


LoginId = Annotated[str, BeforeValidator(_normalize_login_id), StringConstraints(min_length=3, max_length=30, pattern=r"^[a-z0-9][a-z0-9_.-]*$")]
EmailAddress = Annotated[str, BeforeValidator(_normalize_login_id), StringConstraints(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
PersonName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=30)]


class SignupRequest(BaseModel):
    """대표 계정 가입. 이메일이나 아이디 중 하나로 로그인한다."""

    login_id: LoginId | None = None
    email: EmailAddress | None = None
    password: str = Field(min_length=8, max_length=128)
    name: PersonName

    @model_validator(mode="after")
    def one_identifier(self) -> "SignupRequest":
        if (self.login_id is None) == (self.email is None):
            raise ValueError("이메일이나 아이디 중 하나만 입력해 주세요.")
        return self


class LoginRequest(BaseModel):
    # 아이디나 이메일.
    login_id: Annotated[str, BeforeValidator(_normalize_login_id), StringConstraints(min_length=1, max_length=254)]
    password: str = Field(min_length=1, max_length=128)


class AccountUser(BaseModel):
    id: int
    name: str
    # Google 로그인 사용자는 아이디가 없다.
    login_id: str | None
    email: str | None = None
    provider: Literal["password", "google"]


# 프로필
AvatarKey = Literal["paw", "bone", "sun", "moon", "leaf", "heart", "star", "flower"]


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    avatar_key: str
    is_default: bool
    created_at: datetime
    updated_at: datetime
    last_active_at: datetime | None


class ProfileCreate(BaseModel):
    name: PersonName
    avatar_key: AvatarKey = "paw"


class ProfileUpdate(BaseModel):
    name: PersonName | None = None
    avatar_key: AvatarKey | None = None


class ProfileActivity(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    walk_count: int
    total_distance_km: float
    total_minutes: int
    saved_walk_count: int
    # 활동 통계에서 뺀 시연용 산책 수.
    simulated_walk_count: int
    last_walk_at: datetime | None


class ProfileDetail(ProfileRead):
    activity: ProfileActivity


class FamilyMember(BaseModel):
    profile: ProfileBrief
    last_active_at: datetime | None
    activity: ProfileActivity


class FamilyPet(BaseModel):
    id: int
    name: str
    breed: str
    walk_count: int


class FamilyOverview(BaseModel):
    profile_count: int
    max_profiles: int
    totals: ProfileActivity
    members: list[FamilyMember]
    pets: list[FamilyPet]
    recent_walks: list[WalkRead]


class AccountRead(BaseModel):
    authenticated: bool
    auth_required: bool
    google_enabled: bool
    user: AccountUser | None
    profiles: list[ProfileRead] = []
    max_profiles: int = 5
    # 이 세션에서 쓰는 프로필. 서버가 계정 소속을 확인한 값이다.
    current_profile: ProfileRead | None = None
    # 프로필이 여러 개인데 아직 고르지 않았으면 참이다. 이때 프로필이 필요한 API는 428을 돌려준다.
    profile_required: bool = False


class AccountUpdate(BaseModel):
    name: PersonName


class ReauthRequest(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class ReauthRead(BaseModel):
    reauth_required: bool


class AccountDataCounts(BaseModel):
    profiles: int
    pets: int
    walks: int
    feedback: int
    recommendations: int
    saved_walks: int
    photos: int
    personal_courses: int
    shared_walks: int
    community_trails: int
    trail_reviews: int


class AccountSummary(BaseModel):
    provider: Literal["password", "google"]
    # 참이면 탈퇴 전에 본인을 다시 확인해야 한다.
    reauth_required: bool
    session_expires_at: datetime
    session_idle_days: int
    data: AccountDataCounts
    # 자동 백업을 쓰지 않으면 비어 있다.
    backup_retention_days: int | None
