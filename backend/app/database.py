"""SQLAlchemy 엔진과 세션."""
import sqlite3
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event
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
    url = get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
