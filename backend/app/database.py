"""SQLAlchemy 엔진과 세션."""
import sqlite3
from collections.abc import Iterator

from sqlalchemy import Connection, Engine, Table, create_engine, event, func, select, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


@event.listens_for(Engine, "connect")
def _overwrite_deleted_rows(connection, _record) -> None:
    """지운 행을 파일에서 0으로 덮어쓴다. 탈퇴한 보호자의 사진과 경로가 DB 파일의 빈 공간에 남지 않게 한다."""
    if isinstance(connection, sqlite3.Connection):
        connection.execute("PRAGMA secure_delete = ON").close()


def _build_engine():
    settings = get_settings()
    url = settings.database_url
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # 서버 DB는 연결을 재사용한다. DB가 재시작해 끊긴 연결은 꺼내기 전에 확인해 버린다.
    return create_engine(
        url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_recycle=1800,
        pool_pre_ping=True,
    )


def sync_id_sequence(connection: Connection | Session, table: Table) -> None:
    """번호를 직접 넣은 뒤 PostgreSQL의 번호 시퀀스를 가장 큰 번호로 맞춘다. 안 맞추면 다음 행이 같은 번호를 받아 충돌한다.

    SQLite는 가장 큰 번호 다음을 쓰므로 할 일이 없다.
    """
    bind = connection.get_bind() if isinstance(connection, Session) else connection
    if bind.dialect.name != "postgresql":
        return
    highest = connection.execute(select(func.max(table.c.id))).scalar()
    # 행이 없으면 다음 번호가 1이 되게 is_called를 거짓으로 둔다.
    connection.execute(
        text("SELECT setval(pg_get_serial_sequence(:table, 'id'), :value, :called)"),
        {"table": table.name, "value": highest or 1, "called": highest is not None},
    )


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
