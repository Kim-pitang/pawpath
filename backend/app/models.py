"""PawPath ORM 모델."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.clock import now_local
from app.database import Base


class User(Base):
    """보호자. id 1은 로그인하지 않은 요청이 쓰는 시연 보호자이며 비밀번호가 없다."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    # [{"start_hour": 16, "end_hour": 20}, ...]
    available_windows: Mapped[list] = mapped_column(JSON, default=list)
    preferred_duration_min: Mapped[int] = mapped_column(Integer, default=40)
    walks_per_day: Mapped[int] = mapped_column(Integer, default=1)
    login_id: Mapped[str | None] = mapped_column(String(30), nullable=True, unique=True, index=True)
    # scrypt$N$r$p$salt$hash. 시연 보호자는 비어 있어 로그인할 수 없다.
    password_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Google 로그인 사용자의 고유 ID(sub). 이메일은 바뀔 수 있어 표시에만 쓴다.
    google_sub: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    google_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    pets: Mapped[list["Pet"]] = relationship(back_populates="user")


class AuthSession(Base):
    """로그인 세션. 토큰 원문은 쿠키에만 있고 DB에는 SHA-256 값만 둔다."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class Pet(Base):
    __tablename__ = "pets"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(30))
    breed: Mapped[str] = mapped_column(String(50))
    age_years: Mapped[float] = mapped_column(Float)
    weight_kg: Mapped[float] = mapped_column(Float)
    size: Mapped[str] = mapped_column(String(10))
    activity_level: Mapped[str] = mapped_column(String(10))
    personality: Mapped[str] = mapped_column(String(10))
    path_preference: Mapped[str] = mapped_column(String(10))
    heat_sensitivity: Mapped[str] = mapped_column(String(10))
    novelty_reaction: Mapped[str] = mapped_column(String(10))
    preferred_distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    preferred_time_bucket: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # 온라인 학습 상태: 코스 특성 가중치, 시간대별 선호, 누적 피드백 수
    learned_attribute_weights: Mapped[dict] = mapped_column(JSON, default=dict)
    learned_time_buckets: Mapped[dict] = mapped_column(JSON, default=dict)
    feedback_total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    user: Mapped[User] = relationship(back_populates="pets")
    walks: Mapped[list["WalkHistory"]] = relationship(back_populates="pet")
    course_preferences: Mapped[list["PetCoursePreference"]] = relationship(back_populates="pet")


class WalkingCourse(Base):
    __tablename__ = "walking_courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text)
    area: Mapped[str] = mapped_column(String(50))
    start_lat: Mapped[float] = mapped_column(Float)
    start_lng: Mapped[float] = mapped_column(Float)
    distance_km: Mapped[float] = mapped_column(Float)
    duration_min: Mapped[int] = mapped_column(Integer)
    # [[lat, lng], ...]
    route: Mapped[list] = mapped_column(JSON)
    has_park: Mapped[bool] = mapped_column(Boolean)
    park_names: Mapped[list] = mapped_column(JSON, default=list)
    lighting: Mapped[str] = mapped_column(String(10))
    is_paved: Mapped[bool] = mapped_column(Boolean)
    surface_note: Mapped[str] = mapped_column(String(80))
    crowd_level: Mapped[str] = mapped_column(String(10))
    pet_allowed: Mapped[bool] = mapped_column(Boolean)
    pet_rule_note: Mapped[str] = mapped_column(String(120))
    # [{"type": "toilets", "name": "...", "lat": .., "lng": ..}, ...]
    facilities: Mapped[list] = mapped_column(JSON, default=list)
    is_familiar: Mapped[bool] = mapped_column(Boolean)
    shade_level: Mapped[float] = mapped_column(Float)
    difficulty: Mapped[str] = mapped_column(String(10))
    traffic_exposure: Mapped[str] = mapped_column(String(10))
    scenery_tags: Mapped[list] = mapped_column(JSON, default=list)
    data_sources: Mapped[dict] = mapped_column(JSON, default=dict)
    # OSM에서 경로별로 측정한 값: 도로 유형, 조명, 노면, 나무 기록 비율
    environment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 내 산책길로 만든 코스는 주인에게만 보인다. 시드 코스는 비어 있다.
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    saved_walk_id: Mapped[int | None] = mapped_column(ForeignKey("saved_walks.id"), nullable=True)
    # 추천 후보에서 뺀 코스. 산책 기록이 코스를 가리키므로 지우지 않고 끈다.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def is_personal(self) -> bool:
        return self.owner_user_id is not None


class WeatherRecord(Base):
    """시간별 날씨 기록. 실제 날씨의 캐시이자 추천 근거 자료다."""

    __tablename__ = "weather_records"
    __table_args__ = (UniqueConstraint("source", "forecast_time", name="uq_weather_source_time"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(40), index=True)
    forecast_time: Mapped[datetime] = mapped_column(DateTime, index=True)
    temperature: Mapped[float] = mapped_column(Float)
    apparent_temperature: Mapped[float] = mapped_column(Float)
    precipitation_probability: Mapped[float] = mapped_column(Float)
    precipitation_mm: Mapped[float] = mapped_column(Float)
    humidity: Mapped[float] = mapped_column(Float)
    wind_speed: Mapped[float] = mapped_column(Float)
    uv_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_day: Mapped[bool] = mapped_column(Boolean)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pets.id"), index=True)
    top_course_id: Mapped[int | None] = mapped_column(ForeignKey("walking_courses.id"), nullable=True)
    weather_record_id: Mapped[int | None] = mapped_column(ForeignKey("weather_records.id"), nullable=True)
    weather_source: Mapped[str] = mapped_column(String(40))
    weather_scenario: Mapped[str] = mapped_column(String(20))
    walkable: Mapped[bool] = mapped_column(Boolean)
    # 응답 전문. 추천 당시의 점수와 근거를 그대로 보존해 '추천 결과 변화'에 쓴다.
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, index=True)


class WalkHistory(Base):
    __tablename__ = "walk_histories"

    id: Mapped[int] = mapped_column(primary_key=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pets.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("walking_courses.id"), index=True)
    recommendation_id: Mapped[int | None] = mapped_column(ForeignKey("recommendations.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    ended_at: Mapped[datetime] = mapped_column(DateTime)
    duration_min: Mapped[int] = mapped_column(Integer)
    # gps | manual | simulation. 시연용 산책(simulation)은 활동 통계에서 뺀다. 예전 기록은 비어 있다.
    tracking_source: Mapped[str | None] = mapped_column(String(12), nullable=True, default="manual")
    # 실제로 걸은 거리. 비어 있으면 코스 거리를 쓴다.
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)

    pet: Mapped[Pet] = relationship(back_populates="walks")
    course: Mapped[WalkingCourse] = relationship()
    feedback: Mapped["WalkFeedback | None"] = relationship(back_populates="walk", uselist=False)


class WalkFeedback(Base):
    __tablename__ = "walk_feedbacks"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 산책 1회당 피드백 1건. 중복 제출로 학습이 부풀려지는 것을 막는다.
    walk_id: Mapped[int] = mapped_column(ForeignKey("walk_histories.id"), unique=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pets.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("walking_courses.id"), index=True)
    walk_rating: Mapped[int] = mapped_column(Integer)
    pet_rating: Mapped[int] = mapped_column(Integer)
    difficulty: Mapped[str] = mapped_column(String(10))
    weather_rating: Mapped[int] = mapped_column(Integer)
    would_revisit: Mapped[bool] = mapped_column(Boolean)
    memo: Mapped[str] = mapped_column(Text, default="")
    signal: Mapped[float] = mapped_column(Float)
    affinity_before: Mapped[float] = mapped_column(Float)
    affinity_after: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)

    walk: Mapped[WalkHistory] = relationship(back_populates="feedback")
    course: Mapped[WalkingCourse] = relationship()


class PetCoursePreference(Base):
    """반려동물별 코스 선호도. 피드백과 산책 기록으로 갱신되는 학습 상태다."""

    __tablename__ = "pet_course_preferences"
    __table_args__ = (UniqueConstraint("pet_id", "course_id", name="uq_pet_course"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pets.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("walking_courses.id"), index=True)
    affinity: Mapped[float] = mapped_column(Float, default=50.0)
    weighted_sum: Mapped[float] = mapped_column(Float, default=0.0)
    weight_total: Mapped[float] = mapped_column(Float, default=0.0)
    visit_count: Mapped[int] = mapped_column(Integer, default=0)
    feedback_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    pet: Mapped[Pet] = relationship(back_populates="course_preferences")
    course: Mapped[WalkingCourse] = relationship()


class OAuthState(Base):
    """진행 중인 Google 로그인 요청. state는 해시만 두고, 한 번 쓰면 지운다."""

    __tablename__ = "oauth_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    nonce: Mapped[str] = mapped_column(String(100))
    code_verifier: Mapped[str] = mapped_column(String(128))
    next_path: Mapped[str] = mapped_column(String(300))
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class SavedWalk(Base):
    """사용자가 직접 기록하거나 GPX로 가져온 산책길. 추천 코스에 묶인 WalkHistory와 별개다."""

    __tablename__ = "saved_walks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    pet_id: Mapped[int | None] = mapped_column(ForeignKey("pets.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(80))
    memo: Mapped[str] = mapped_column(Text, default="")
    # recorded | imported
    source_type: Mapped[str] = mapped_column(String(10))
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    distance_m: Mapped[float] = mapped_column(Float)
    # 시각이 없는 GPX는 시간과 속도를 알 수 없어 비워 둔다.
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    average_speed_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    has_timestamps: Mapped[bool] = mapped_column(Boolean, default=True)
    point_count: Mapped[int] = mapped_column(Integer)
    # private | link | public
    visibility: Mapped[str] = mapped_column(String(10), default="private")
    share_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    share_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    share_memo: Mapped[bool] = mapped_column(Boolean, default=False)
    # 네트워크 재시도 때 같은 산책이 두 번 저장되지 않게 하는 값
    client_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    route_hash: Mapped[str] = mapped_column(String(64), index=True)
    # 목록 썸네일용으로 줄인 경로: [[[lat, lng], ...], ...]
    preview: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    pet: Mapped[Pet | None] = relationship()
    course: Mapped[WalkingCourse | None] = relationship(uselist=False, viewonly=True)
    points: Mapped[list["SavedWalkPoint"]] = relationship(
        back_populates="walk", cascade="all, delete-orphan", order_by="SavedWalkPoint.sequence"
    )
    photos: Mapped[list["SavedWalkPhoto"]] = relationship(
        back_populates="walk", cascade="all, delete-orphan", order_by="SavedWalkPhoto.id"
    )


class SavedWalkPoint(Base):
    """산책길의 GPS 지점. 파일과 기록의 순서를 sequence로 보존한다."""

    __tablename__ = "saved_walk_points"
    __table_args__ = (Index("ix_saved_walk_points_walk_sequence", "walk_id", "sequence", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    walk_id: Mapped[int] = mapped_column(ForeignKey("saved_walks.id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(Integer)
    # 일시정지나 GPX trkseg 단위. 구간 사이는 거리에 넣지 않고 선도 잇지 않는다.
    segment: Mapped[int] = mapped_column(Integer, default=0)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    altitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)

    walk: Mapped[SavedWalk] = relationship(back_populates="points")


class SavedWalkPhoto(Base):
    """산책길 사진. 위치가 담길 수 있는 메타데이터를 지운 뒤 저장하고, 공유 화면에는 내보내지 않는다."""

    __tablename__ = "saved_walk_photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    walk_id: Mapped[int] = mapped_column(ForeignKey("saved_walks.id", ondelete="CASCADE"), index=True)
    content_type: Mapped[str] = mapped_column(String(20))
    # 목록과 상세에서 사진 정보만 읽을 때 원본까지 불러오지 않게 미룬다.
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)

    walk: Mapped[SavedWalk] = relationship(back_populates="photos")

