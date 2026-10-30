"""API 요청과 응답 스키마."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Size = Literal["small", "medium", "large"]
Level = Literal["low", "medium", "high"]
Personality = Literal["active", "timid", "curious"]
PathPreference = Literal["familiar", "new"]
NoveltyReaction = Literal["calm", "cautious", "anxious"]
Difficulty = Literal["easy", "just_right", "hard"]
WeatherScenario = Literal["live", "rain_later", "heatwave", "cold", "heavy_rain"]


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


class RecommendationRequest(BaseModel):
    pet_id: int
    weather_scenario: WeatherScenario = "live"


class WalkCreate(BaseModel):
    pet_id: int
    course_id: int
    recommendation_id: int | None = None
    duration_min: int = Field(ge=1, le=600)
    started_at: datetime | None = None


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
