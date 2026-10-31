"""기존 DB에 새 선택 컬럼을 더한다.

create_all은 이미 있는 테이블을 바꾸지 않으므로, 예전 DB를 그대로 열면 새 컬럼이 없어 오류가 난다.
모두 비어 있어도 되는 컬럼이라 기존 데이터에 영향을 주지 않는다.
"""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.database import Base

ADDED_COLUMNS = {
    "pets": (("preferred_distance_km", "FLOAT"), ("preferred_time_bucket", "VARCHAR(10)")),
    "walking_courses": (("environment", "JSON"),),
    "walk_histories": (("tracking_source", "VARCHAR(12)"), ("distance_km", "FLOAT")),
    "users": (("login_id", "VARCHAR(30)"), ("password_hash", "VARCHAR(200)"), ("google_sub", "VARCHAR(64)"), ("google_email", "VARCHAR(254)")),
}
# 컬럼을 나중에 더하면 create_all이 만드는 고유 색인이 빠지므로 따로 만든다. 이미 있으면 건너뛴다.
ADDED_UNIQUE_INDEXES = (("ix_users_login_id", "users", "login_id"), ("ix_users_google_sub", "users", "google_sub"))


def ensure_schema(engine: Engine) -> list[str]:
    """테이블을 만들고 빠진 컬럼을 추가한다. 추가한 컬럼 이름을 돌려준다."""
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
    return added
