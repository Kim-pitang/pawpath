"""기존 DB를 지금 구조로 올린다.

create_all은 이미 있는 테이블을 바꾸지 않으므로, 예전 DB를 그대로 열면 새 컬럼이 없어 오류가 난다.
모두 비어 있어도 되는 컬럼이라 기존 데이터에 영향을 주지 않는다. 프로필이 없던 시절의 데이터는 각 계정의
대표 프로필로 잇는다. 여러 번 실행해도 비어 있는 행만 채우고, 중간에 실패하면 채우던 내용을 함께 되돌린다.
"""
from sqlalchemy import func, insert, inspect, literal, select, text, update
from sqlalchemy.engine import Connection, Engine

from app.clock import now_local
from app.database import Base
from app.models import DEFAULT_AVATAR, Pet, Profile, Recommendation, SavedWalk, User, WalkFeedback, WalkHistory

ADDED_COLUMNS = {
    "pets": (("preferred_distance_km", "FLOAT"), ("preferred_time_bucket", "VARCHAR(10)")),
    "walking_courses": (("environment", "JSON"), ("owner_user_id", "INTEGER"), ("saved_walk_id", "INTEGER"), ("is_active", "BOOLEAN DEFAULT TRUE"), ("community_trail_id", "INTEGER")),
    "walk_histories": (("tracking_source", "VARCHAR(12)"), ("distance_km", "FLOAT"), ("profile_id", "INTEGER")),
    "users": (("login_id", "VARCHAR(30)"), ("password_hash", "VARCHAR(200)"), ("google_sub", "VARCHAR(64)"), ("google_email", "VARCHAR(254)"), ("email", "VARCHAR(254)")),
    "auth_sessions": (("last_seen_at", "TIMESTAMP"), ("reauthenticated_at", "TIMESTAMP"), ("profile_id", "INTEGER")),
    "oauth_states": (("reauth_user_id", "INTEGER"),),
    "saved_walks": (("profile_id", "INTEGER"),),
    "recommendations": (("profile_id", "INTEGER"), ("algorithm_version", "VARCHAR(20)"), ("weather_fetched_at", "TIMESTAMP")),
    "walk_feedbacks": (("profile_id", "INTEGER"),),
}
# 컬럼을 나중에 더하면 create_all이 만드는 색인이 빠지므로 따로 만든다. 이미 있으면 건너뛴다.
ADDED_UNIQUE_INDEXES = (
    ("ix_users_login_id", "users", "login_id"),
    ("ix_users_google_sub", "users", "google_sub"),
    ("ix_users_email", "users", "email"),
    ("ix_walking_courses_community_trail_id", "walking_courses", "community_trail_id"),
)
ADDED_INDEXES = (
    ("ix_auth_sessions_profile_id", "auth_sessions", "profile_id"),
    ("ix_walk_histories_profile_id", "walk_histories", "profile_id"),
    ("ix_saved_walks_profile_id", "saved_walks", "profile_id"),
    ("ix_recommendations_profile_id", "recommendations", "profile_id"),
    ("ix_walk_feedbacks_profile_id", "walk_feedbacks", "profile_id"),
)


# 마이그레이션 전후로 행 수를 비교하는 테이블. 프로필을 잇는 작업은 행을 더하기만 해야 한다.
COUNTED_TABLES = (
    "users",
    "profiles",
    "pets",
    "walk_histories",
    "walk_feedbacks",
    "recommendations",
    "saved_walks",
    "saved_walk_points",
    "saved_walk_photos",
    "auth_sessions",
    "community_trails",
)


def row_counts(engine: Engine) -> dict[str, int]:
    tables = set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        return {name: connection.execute(text(f"SELECT count(*) FROM {name}")).scalar_one() for name in COUNTED_TABLES if name in tables}


def needs_migration(engine: Engine) -> bool:
    """이미 데이터가 있는 DB에서 테이블이나 컬럼을 더해야 하면 참이다. 새 DB는 백업할 것이 없어 거짓이다."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "users" not in tables:
        return False
    if "profiles" not in tables:
        return True
    for table, columns in ADDED_COLUMNS.items():
        existing = {column["name"] for column in inspector.get_columns(table)} if table in tables else set()
        if table in tables and any(name not in existing for name, _ in columns):
            return True
    return False


def backfill_profiles(connection: Connection) -> int:
    """대표 프로필이 없는 계정에 하나씩 만들고, 프로필이 비어 있는 기록을 그 계정의 대표 프로필로 잇는다. 만든 수를 돌려준다."""
    now = now_local()
    has_default = select(Profile.user_id).where(Profile.is_default.is_(True))
    created = connection.execute(
        insert(Profile).from_select(
            ["user_id", "name", "avatar_key", "is_default", "available_windows", "preferred_duration_min", "walks_per_day", "created_at", "updated_at"],
            select(
                User.id,
                func.substr(User.name, 1, 30),
                literal(DEFAULT_AVATAR),
                literal(True),
                User.available_windows,
                User.preferred_duration_min,
                User.walks_per_day,
                User.created_at,
                literal(now),
            ).where(User.id.not_in(has_default)),
        )
    ).rowcount
    for model in (WalkHistory, Recommendation, WalkFeedback):
        default_of_pet_owner = (
            select(Profile.id).join(Pet, Pet.user_id == Profile.user_id).where(Pet.id == model.pet_id, Profile.is_default.is_(True)).correlate(model).scalar_subquery()
        )
        connection.execute(update(model).where(model.profile_id.is_(None)).values(profile_id=default_of_pet_owner))
    default_of_owner = select(Profile.id).where(Profile.user_id == SavedWalk.user_id, Profile.is_default.is_(True)).correlate(SavedWalk).scalar_subquery()
    # 마지막 수정 시각이 이 작업 시각으로 바뀌지 않게 그대로 둔다.
    connection.execute(update(SavedWalk).where(SavedWalk.profile_id.is_(None)).values(profile_id=default_of_owner, updated_at=SavedWalk.updated_at))
    return created


def ensure_schema(engine: Engine) -> list[str]:
    """테이블을 만들고 빠진 컬럼을 추가한 뒤 프로필을 잇는다. 추가한 컬럼 이름을 돌려준다."""
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    added: list[str] = []
    with engine.begin() as connection:
        for table, columns in ADDED_COLUMNS.items():
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, column_type in columns:
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}"))
                    added.append(f"{table}.{name}")
        for index, table, column in ADDED_UNIQUE_INDEXES:
            connection.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS {index} ON {table} ({column})"))
        for index, table, column in ADDED_INDEXES:
            connection.execute(text(f"CREATE INDEX IF NOT EXISTS {index} ON {table} ({column})"))
    with engine.begin() as connection:
        backfill_profiles(connection)
    return added
