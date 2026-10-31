"""Alembic 리비전과 모델이 같은 구조를 만드는지, 예전 DB를 데이터 손실 없이 올리는지 확인한다. 테스트 DB에서 돈다."""
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, select, text

from app.database import Base, SessionLocal, engine
from app.migrations import alembic_config, current_revision, ensure_schema, head_revision, needs_migration, row_counts
from app.models import User
from app.seed import seed_all


def drop_everything() -> None:
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))


def differences() -> list:
    with engine.connect() as connection:
        return compare_metadata(MigrationContext.configure(connection), Base.metadata)


def revision() -> str | None:
    with engine.connect() as connection:
        return current_revision(connection)


def test_new_database_is_built_by_the_revisions_exactly_like_the_models():
    drop_everything()
    assert needs_migration(engine) is False
    ensure_schema(engine)
    assert revision() == head_revision()
    assert differences() == []


def test_database_made_before_alembic_keeps_its_rows_and_is_marked():
    drop_everything()
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_all(db)
    before = row_counts(engine)
    assert needs_migration(engine) is True
    ensure_schema(engine)
    assert revision() == head_revision()
    assert row_counts(engine) == before
    assert differences() == []
    # 다시 열어도 바꿀 것이 없다.
    assert needs_migration(engine) is False


def test_revisions_can_be_rolled_back_and_applied_again():
    drop_everything()
    ensure_schema(engine)
    with engine.begin() as connection:
        command.downgrade(alembic_config(connection), "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    with engine.begin() as connection:
        command.upgrade(alembic_config(connection), "head")
    assert differences() == []


def test_new_accounts_do_not_collide_with_the_seeded_account():
    """시연 보호자는 번호 1을 직접 받는다. PostgreSQL 시퀀스가 따라오지 않으면 다음 가입이 1을 받아 충돌한다."""
    drop_everything()
    ensure_schema(engine)
    with SessionLocal() as db:
        seed_all(db)
        db.add(User(name="새 보호자", available_windows=[]))
        db.commit()
        assert sorted(db.scalars(select(User.id))) == [1, 2]
