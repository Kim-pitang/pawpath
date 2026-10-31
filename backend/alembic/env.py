"""Alembic 실행 환경. DB 주소는 앱과 같은 DATABASE_URL을 쓴다.

서버가 켜질 때는 app.migrations가 연결을 넘겨 같은 트랜잭션 안에서 돌린다. 명령줄에서는 직접 연결한다.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app import models  # noqa: F401  테이블 등록을 위해 불러온다
from app.config import get_settings
from app.database import Base

config = context.config
target_metadata = Base.metadata
# 서버 안에서 돌 때는 uvicorn의 로그 설정을 덮지 않는다.
if config.config_file_name and "connection" not in config.attributes:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def run_migrations_offline() -> None:
    """DB에 붙지 않고 SQL만 출력한다. alembic upgrade head --sql"""
    url = get_settings().database_url
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, render_as_batch=url.startswith("sqlite"))
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    # SQLite는 ALTER TABLE이 약해 컬럼을 바꿀 때 표를 새로 만들어 옮기는 batch 모드가 필요하다.
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = create_engine(get_settings().database_url)
    try:
        with engine.connect() as connection:
            _run(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
