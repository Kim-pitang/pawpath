"""추천 엔진 입출력 자료형."""
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class PetProfile:
    name: str
    age_years: float
    weight_kg: float
    size: str  # small | medium | large
    activity_level: str  # low | medium | high
    personality: str  # active | timid | curious
    path_preference: str  # familiar | new
    heat_sensitivity: str  # low | medium | high
    novelty_reaction: str  # calm | cautious | anxious
    preferred_distance_km: float | None = None
    preferred_time_bucket: str | None = None  # morning | lunch | afternoon | evening


@dataclass(frozen=True)
class PetFeatures:
    """프로필에서 계산한 추천용 특성값."""

    life_stage: str  # puppy | adult | senior
    ideal_walk_min: int
    ideal_distance_km: float
    novelty_tolerance: float  # 0(낯선 길 기피) ~ 1(새로운 길 선호)
    crowd_tolerance: float  # 0(혼잡 기피) ~ 1(혼잡 무관)
    hill_tolerance: float  # 0 ~ 1
    comfort_low: float  # 쾌적 체감온도 하한(°C)
    comfort_high: float  # 쾌적 체감온도 상한(°C)
    unsafe_cold: float  # 이 체감온도 이하는 산책 제외
    unsafe_heat: float  # 이 체감온도 이상은 산책 제외
    preferred_distance_km: float | None = None
    preferred_time_bucket: str | None = None


@dataclass(frozen=True)
class HourWeather:
    time: datetime
    temperature: float
    apparent_temperature: float
    precipitation_probability: float
    precipitation_mm: float
    humidity: float
    wind_speed: float
    uv_index: float | None
    is_day: bool
    # 미세먼지(µg/m³). 지금은 받아 오는 제공자가 없어 비어 있고, 안전 평가에서 '확인 불가'로 표시한다.
    pm10: float | None = None
    pm2_5: float | None = None


@dataclass(frozen=True)
class TimeWindow:
    start_hour: int
    end_hour: int  # 미포함. 16~20이면 19시대까지 출발하고 20시 전에 마친다.


@dataclass(frozen=True)
class Schedule:
    windows: tuple[TimeWindow, ...]
    preferred_duration_min: int
    walks_per_day: int = 1


@dataclass(frozen=True)
class CourseData:
    id: int
    name: str
    distance_km: float
    duration_min: int
    has_park: bool
    lighting: str  # good | partial | poor | unknown
    is_paved: bool
    crowd_level: str  # low | medium | high
    pet_allowed: bool
    is_familiar: bool
    shade_level: float  # 0 ~ 1
    difficulty: str  # easy | moderate | hard
    traffic_exposure: str  # low | medium | high
    scenery_tags: tuple[str, ...] = ()
    facility_counts: dict[str, int] = field(default_factory=dict)
    # OSM에서 수집한 실측값. 없으면 안전 평가에서 '확인 불가'로 다룬다.
    environment: dict = field(default_factory=dict)
    # 측정도 팀 추정도 없는 속성 이름. 내 산책길처럼 값을 알 수 없을 때 중립값으로 계산하고 '확인 불가'로 표시한다.
    unknown: frozenset[str] = frozenset()
    # [(lat, lng), ...]. 비슷한 코스를 TOP 3에 함께 올리지 않는 데 쓴다. 없으면 겹침을 판단하지 않는다.
    route: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class WalkSample:
    """선호 프로필을 만드는 산책 1회. 피드백이 없으면 signal이 비어 있다."""

    course_id: int
    distance_km: float
    expected_min: int
    actual_min: int
    start_hour: int
    tracking_source: str  # gps | manual | simulation
    signal: float | None = None
    difficulty: str | None = None  # easy | just_right | hard


@dataclass(frozen=True)
class CoursePreference:
    affinity: float = 50.0
    weighted_sum: float = 0.0
    weight_total: float = 0.0
    visit_count: int = 0
    feedback_count: int = 0


@dataclass(frozen=True)
class BucketPreference:
    weighted_sum: float = 0.0
    weight_total: float = 0.0


@dataclass(frozen=True)
class PreferenceState:
    """반려동물 한 마리의 학습 상태."""

    courses: dict[int, CoursePreference] = field(default_factory=dict)
    attribute_weights: dict[str, float] = field(default_factory=dict)
    time_buckets: dict[str, BucketPreference] = field(default_factory=dict)
    feedback_total: int = 0
    # 아래는 v2가 쓰는 행동 기록. 저장된 학습 상태가 아니라 산책 기록에서 매번 다시 계산한다.
    walks: tuple[WalkSample, ...] = ()
    # 최근 추천 TOP 3에 있었지만, 그날 다른 코스를 걸은 날 수. 클릭만 안 한 날은 세지 않는다.
    skipped_days: dict[int, int] = field(default_factory=dict)


@dataclass(frozen=True)
class FeedbackInput:
    walk_rating: int  # 1 ~ 5
    pet_rating: int  # 1 ~ 5
    difficulty: str  # easy | just_right | hard
    weather_rating: int  # 1 ~ 5
    would_revisit: bool


@dataclass(frozen=True)
class SlotEvaluation:
    """특정 출발 시각에 특정 시간만큼 산책할 때의 평가."""

    start: datetime
    end: datetime
    duration_min: int
    window: TimeWindow
    weather: HourWeather
    score: float
    comfort: float
    components: dict[str, float]
    unsafe_reason: str | None
    rain_overlap_min: int
    rain_onset: datetime | None
    before_rain: bool
    is_dark: bool
    fits_window: bool
    ideal_factor: float  # 날씨에 따른 권장 산책량 배율


@dataclass(frozen=True)
class FactorScore:
    key: str
    label: str
    score: float
    weight: float
    contribution: float
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class SafetyItem:
    key: str
    label: str
    status: str  # ok | caution | danger | unverified
    score: float | None
    value: str
    source: str  # forecast | demo | observed | estimated | unknown
    source_label: str
    detail: str | None


@dataclass(frozen=True)
class SafetyAssessment:
    score: float
    level: str  # good | caution | danger | blocked
    items: tuple[SafetyItem, ...]
    risks: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    unverified: tuple[str, ...]
    penalty: float
    disclaimer: str
    # 점수에 들어간 항목의 출처별 비중과 데이터 기준일. data_quality_payload 참고.
    data_quality: dict = field(default_factory=dict)
    # 위험 수준일 때 화면 맨 위에 보여 줄 강한 경고
    warning: str | None = None


@dataclass(frozen=True)
class Explanation:
    summary: str
    details: tuple[str, ...]
    cautions: tuple[str, ...]
    # 안전 지수에 나오지 않는 주의사항. 화면에서 같은 경고를 두 번 보여 주지 않기 위해 따로 둔다.
    other_cautions: tuple[str, ...] = ()
    # 항목별 추천 근거: ({"key", "label", "text", "source"}, ...). 데이터가 있는 항목만 넣는다.
    basis: tuple[dict, ...] = ()


@dataclass(frozen=True)
class GroupScore:
    """v2 개인화 점수의 평가 묶음. 데이터가 없는 묶음은 available이 거짓이고 가중치가 0이다."""

    key: str
    label: str
    score: float | None
    weight: float
    contribution: float
    evidence: tuple[str, ...]
    available: bool = True
    source: str = ""


@dataclass(frozen=True)
class CourseRecommendation:
    rank: int
    course: CourseData
    slot: SlotEvaluation
    total_score: float
    baseline_score: float
    baseline_rank: int
    factors: tuple[FactorScore, ...]
    explanation: Explanation
    preference_score: float
    safety: SafetyAssessment
    alternative: CourseData | None = None
    # v2: 개인화 점수와 감점을 나눠 둔다. total_score = personalization_score - safety_penalty - skip_penalty
    personalization_score: float | None = None
    safety_penalty: float = 0.0
    skip_penalty: float = 0.0
    groups: tuple[GroupScore, ...] = ()
    # 이미 다녀온 코스만 남을 때 아직 안 가 본 코스로 바꿔 넣은 자리
    exploration: bool = False
    # 경로가 많이 겹치는 상위 코스. 다른 후보가 없어 함께 올렸을 때만 채운다.
    similar_to: str | None = None


@dataclass(frozen=True)
class ExcludedCourse:
    course: CourseData
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class CandidateScore:
    """추천 이력에 남기는 후보 코스 1개의 점수. TOP 3 밖의 코스와 제외된 코스도 남긴다."""

    course_id: int
    rank: int | None
    position: int | None
    total_score: float | None
    personalization_score: float | None
    safety_penalty: float
    skip_penalty: float
    safety_level: str | None
    safety_score: float | None
    groups: dict
    data_quality: dict
    excluded_reasons: tuple[str, ...] = ()
    duplicate_of: int | None = None
    exploration: bool = False


@dataclass(frozen=True)
class TimeRecommendation:
    recommended_duration_min: int
    best_slots: tuple[SlotEvaluation, ...]
    all_slots: tuple[SlotEvaluation, ...]


@dataclass(frozen=True)
class RecommendationResult:
    walkable: bool
    features: PetFeatures
    time: TimeRecommendation
    courses: tuple[CourseRecommendation, ...]
    weights: dict[str, float]
    blocked_reasons: tuple[str, ...]
    indoor_alternatives: tuple[str, ...]
    excluded: tuple[ExcludedCourse, ...] = ()
    ranker: str = "weighted-sum"
    algorithm_version: str = "rule-v1"
    # ok | unsafe | no_forecast | no_window | no_candidates. 산책을 권하지 않는 이유를 구분한다.
    status: str = "ok"
    # 날씨를 확인하지 못한 경우처럼 추천 전체에 걸리는 데이터 문제
    data_notice: str | None = None
    candidates: tuple[CandidateScore, ...] = ()
