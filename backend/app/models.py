"""PawPath ORM 모델."""
from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.clock import now_local
from app.database import Base

DEFAULT_AVATAR = "paw"


class User(Base):
    """대표 계정(가족 계정). 로그인 주체이고, 반려동물과 산책길의 주인이다. 그 안에서 누가 썼는지는 Profile로 구분한다.

    id 1은 로그인하지 않은 요청이 쓰는 시연 보호자이며 비밀번호가 없다.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    # [{"start_hour": 16, "end_hour": 20}, ...]
    available_windows: Mapped[list] = mapped_column(JSON, default=list)
    preferred_duration_min: Mapped[int] = mapped_column(Integer, default=40)
    walks_per_day: Mapped[int] = mapped_column(Integer, default=1)
    # login_id, email, password_hash는 비밀번호 로그인을 없애기 전의 컬럼이다. 코드는 더 이상 읽거나 쓰지 않고, 지우는 일은 Alembic 리비전으로 따로 한다.
    login_id: Mapped[str | None] = mapped_column(String(30), nullable=True, unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True, unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Google 로그인 사용자의 고유 ID(sub). 이메일은 바뀔 수 있어 표시에만 쓴다.
    google_sub: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    google_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    pets: Mapped[list["Pet"]] = relationship(back_populates="user")
    profiles: Mapped[list["Profile"]] = relationship(back_populates="user")


class Profile(Base):
    """대표 계정 안의 보호자 프로필. 따로 로그인하지 않고, 지워도 기록이 누구의 것인지 남도록 행을 지우지 않는다."""

    __tablename__ = "profiles"
    # 계정마다 대표 프로필은 하나뿐이다.
    __table_args__ = (Index("ux_profiles_one_default", "user_id", unique=True, sqlite_where=text("is_default"), postgresql_where=text("is_default")),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(30))
    avatar_key: Mapped[str] = mapped_column(String(20), default=DEFAULT_AVATAR)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # 산책할 수 있는 시간은 사람마다 달라 프로필마다 둔다. 추천과 날씨 조회가 이 값을 쓴다.
    available_windows: Mapped[list] = mapped_column(JSON, default=list)
    preferred_duration_min: Mapped[int] = mapped_column(Integer, default=40)
    walks_per_day: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship(back_populates="profiles")

    @property
    def deleted(self) -> bool:
        return self.deleted_at is not None


class AuthSession(Base):
    """로그인 세션. 토큰 원문은 쿠키에만 있고 DB에는 SHA-256 값만 둔다."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    # 마지막으로 쓴 시각. 비어 있으면 만든 시각으로 본다. 오래 쓰지 않은 세션을 끝내는 데 쓴다.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 탈퇴처럼 되돌릴 수 없는 작업 전에 본인을 다시 확인한 시각. 비어 있으면 로그인한 시각으로 본다.
    reauthenticated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 이 세션에서 고른 프로필. 쓸 때마다 이 계정 소속인지 다시 확인한다. 비어 있으면 아직 고르지 않았다.
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id", ondelete="SET NULL"), nullable=True, index=True)


class Pet(Base):
    """반려동물. 대표 계정의 공용 자산이라 어느 프로필에서나 고를 수 있고, 학습한 취향도 함께 쓴다."""

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
    # 커뮤니티 산책길로 길 안내를 받으려고 만든 코스. 산책길이 공개인 동안 누구나 볼 수 있고 추천 후보에는 들어가지 않는다.
    community_trail_id: Mapped[int | None] = mapped_column(ForeignKey("community_trails.id"), nullable=True, unique=True, index=True)

    @property
    def is_personal(self) -> bool:
        return self.owner_user_id is not None and self.community_trail_id is None


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
    # 추천을 받은 프로필. 대표 계정은 pet_id로 이어진다.
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id"), nullable=True, index=True)
    top_course_id: Mapped[int | None] = mapped_column(ForeignKey("walking_courses.id"), nullable=True)
    weather_record_id: Mapped[int | None] = mapped_column(ForeignKey("weather_records.id"), nullable=True)
    weather_source: Mapped[str] = mapped_column(String(40))
    weather_scenario: Mapped[str] = mapped_column(String(20))
    walkable: Mapped[bool] = mapped_column(Boolean)
    # 응답 전문. 추천 당시의 점수와 근거를 그대로 보존해 '추천 결과 변화'에 쓴다.
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, index=True)
    # 점수를 낸 알고리즘(rule-v1, rule-v2). 비어 있으면 버전을 남기기 전의 기록이며 rule-v1이다.
    algorithm_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 추천에 쓴 예보를 받아 온 시각. 시연용 시나리오는 추천 시각과 같다.
    weather_fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WalkHistory(Base):
    __tablename__ = "walk_histories"

    id: Mapped[int] = mapped_column(primary_key=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pets.id"), index=True)
    # 산책을 한 프로필. 대표 계정은 pet_id로 이어진다. 프로필이 없던 시절의 기록은 대표 프로필로 옮겼다.
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id"), nullable=True, index=True)
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
    profile: Mapped[Profile | None] = relationship()
    course: Mapped[WalkingCourse] = relationship()
    feedback: Mapped["WalkFeedback | None"] = relationship(back_populates="walk", uselist=False)


class WalkFeedback(Base):
    __tablename__ = "walk_feedbacks"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 산책 1회당 피드백 1건. 중복 제출로 학습이 부풀려지는 것을 막는다.
    walk_id: Mapped[int] = mapped_column(ForeignKey("walk_histories.id"), unique=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pets.id"), index=True)
    # 산책을 한 프로필. 산책 기록의 값을 그대로 옮겨 둔다.
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id"), nullable=True, index=True)
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
    # 로그인이 아니라 본인 재확인일 때 그 보호자. 다른 Google 계정으로 돌아오면 거부한다.
    reauth_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SavedWalk(Base):
    """사용자가 직접 기록하거나 GPX로 가져온 산책길. 추천 코스에 묶인 WalkHistory와 별개다."""

    __tablename__ = "saved_walks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # 산책길을 만든 프로필. 고치고 지울 수 있는 사람을 가른다.
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id"), nullable=True, index=True)
    pet_id: Mapped[int | None] = mapped_column(ForeignKey("pets.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(80))
    memo: Mapped[str] = mapped_column(Text, default="")
    # recorded | imported | generated
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
    profile: Mapped[Profile | None] = relationship()
    course: Mapped[WalkingCourse | None] = relationship(uselist=False, viewonly=True)
    points: Mapped[list["SavedWalkPoint"]] = relationship(
        back_populates="walk", cascade="all, delete-orphan", order_by="SavedWalkPoint.sequence"
    )
    photos: Mapped[list["SavedWalkPhoto"]] = relationship(
        back_populates="walk", cascade="all, delete-orphan", order_by="SavedWalkPhoto.id"
    )
    community_trail: Mapped["CommunityTrail | None"] = relationship(back_populates="walk", uselist=False, cascade="all, delete-orphan")


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


class CommunityTrail(Base):
    """커뮤니티에 공유한 산책길. 좌표는 saved_walk_points에 한 벌만 두고, 여기에는 출발점과 도착점 주변을 가린 공개용 값만 둔다."""

    __tablename__ = "community_trails"
    __table_args__ = (Index("ix_community_trails_visibility_created", "visibility", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # 산책길 하나는 한 번만 공유한다.
    saved_walk_id: Mapped[int] = mapped_column(ForeignKey("saved_walks.id", ondelete="CASCADE"), unique=True)
    title: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    # 사진은 DB에 있어 주소 대신 사진 번호를 둔다. 고른 한 장만 공개된다.
    cover_photo_id: Mapped[int | None] = mapped_column(ForeignKey("saved_walk_photos.id", ondelete="SET NULL"), nullable=True)
    # public | private. 비공개여도 좋아요와 후기는 남겨 두어 다시 공개하면 돌아온다.
    visibility: Mapped[str] = mapped_column(String(10), default="public")
    region: Mapped[str] = mapped_column(String(50), index=True)
    features: Mapped[list] = mapped_column(JSON, default=list)
    suitable_for: Mapped[list] = mapped_column(JSON, default=list)
    # 원본 출발점과 도착점에서 이 반경 안의 지점을 공개하지 않는다. 주인에게만 보여 준다.
    hide_radius_m: Mapped[int] = mapped_column(Integer, default=200)
    # 아래는 가린 뒤의 경로로 계산한 값이다. 목록을 그릴 때 전체 지점을 읽지 않으려고 저장한다.
    distance_m: Mapped[float] = mapped_column(Float, index=True)
    estimated_min: Mapped[int] = mapped_column(Integer, index=True)
    elevation_gain_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    # easy | moderate | hard
    difficulty: Mapped[str] = mapped_column(String(10), index=True)
    start_lat: Mapped[float] = mapped_column(Float)
    start_lng: Mapped[float] = mapped_column(Float)
    end_lat: Mapped[float] = mapped_column(Float)
    end_lng: Mapped[float] = mapped_column(Float)
    start_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    end_label: Mapped[str | None] = mapped_column(String(100), nullable=True)
    preview: Mapped[list] = mapped_column(JSON, default=list)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    author: Mapped[User] = relationship()
    walk: Mapped[SavedWalk] = relationship(back_populates="community_trail")
    likes: Mapped[list["TrailLike"]] = relationship(back_populates="trail", cascade="all, delete-orphan")
    bookmarks: Mapped[list["TrailBookmark"]] = relationship(back_populates="trail", cascade="all, delete-orphan")
    reviews: Mapped[list["TrailReview"]] = relationship(back_populates="trail", cascade="all, delete-orphan")


class TrailLike(Base):
    __tablename__ = "trail_likes"
    __table_args__ = (UniqueConstraint("user_id", "community_trail_id", name="uq_trail_like_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    community_trail_id: Mapped[int] = mapped_column(ForeignKey("community_trails.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)

    trail: Mapped[CommunityTrail] = relationship(back_populates="likes")


class TrailBookmark(Base):
    __tablename__ = "trail_bookmarks"
    __table_args__ = (UniqueConstraint("user_id", "community_trail_id", name="uq_trail_bookmark_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    community_trail_id: Mapped[int] = mapped_column(ForeignKey("community_trails.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)

    trail: Mapped[CommunityTrail] = relationship(back_populates="bookmarks")


class TrailReview(Base):
    """산책길 후기. 보호자 한 명이 산책길마다 하나만 남긴다. 산책 인증 여부는 산책 기록에서 읽을 때 계산한다."""

    __tablename__ = "trail_reviews"
    __table_args__ = (
        UniqueConstraint("user_id", "community_trail_id", name="uq_trail_review_user"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_trail_review_rating"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # 탈퇴하면 보호자의 글도 함께 지운다. 평점은 읽을 때 집계하므로 바로 반영된다.
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    community_trail_id: Mapped[int] = mapped_column(ForeignKey("community_trails.id", ondelete="CASCADE"), index=True)
    rating: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)

    author: Mapped[User] = relationship()
    trail: Mapped[CommunityTrail] = relationship(back_populates="reviews")
    photos: Mapped[list["TrailReviewPhoto"]] = relationship(
        back_populates="review", cascade="all, delete-orphan", order_by="TrailReviewPhoto.id"
    )


class TrailReviewPhoto(Base):
    """후기 사진. 산책길 사진과 같은 방법으로 메타데이터를 지운 뒤 저장한다."""

    __tablename__ = "trail_review_photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("trail_reviews.id", ondelete="CASCADE"), index=True)
    content_type: Mapped[str] = mapped_column(String(20))
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    size_bytes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)

    review: Mapped[TrailReview] = relationship(back_populates="photos")



class RecommendationItem(Base):
    """추천 1건의 후보 코스별 점수. TOP 3 밖의 후보와 제외된 코스도 남겨 버전별 비교와 편중 점검에 쓴다."""

    __tablename__ = "recommendation_items"
    __table_args__ = (UniqueConstraint("recommendation_id", "course_id", name="uq_recommendation_item_course"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id", ondelete="CASCADE"), index=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pets.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("walking_courses.id"), index=True)
    algorithm_version: Mapped[str] = mapped_column(String(20))
    # TOP 3 안의 순위. 밖이면 비어 있다.
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 안전 단계와 점수로 정렬한 후보 순서. 제외된 코스는 비어 있다.
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    personalization_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    safety_penalty: Mapped[float] = mapped_column(Float, default=0.0)
    skip_penalty: Mapped[float] = mapped_column(Float, default=0.0)
    safety_level: Mapped[str | None] = mapped_column(String(10), nullable=True)
    safety_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # {"pet_fit": {"score": 90.1, "weight": 0.4167}, ...}
    group_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    data_quality: Mapped[dict] = mapped_column(JSON, default=dict)
    excluded_reasons: Mapped[list] = mapped_column(JSON, default=list)
    duplicate_of: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exploration: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)


class RecommendationEvent(Base):
    """추천 뒤 행동. 산책 완료와 피드백은 산책 기록에서 알 수 있어, 서버가 모르는 선택과 출발만 남긴다."""

    __tablename__ = "recommendation_events"
    __table_args__ = (UniqueConstraint("recommendation_id", "course_id", "event", name="uq_recommendation_event"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id", ondelete="CASCADE"), index=True)
    pet_id: Mapped[int] = mapped_column(ForeignKey("pets.id"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("walking_courses.id"))
    # select: 추천 카드에서 '이 코스로 산책'을 누름, start: 길 안내에서 산책을 시작함
    event: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
