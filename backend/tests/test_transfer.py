"""SQLite → PostgreSQL 이전. TEST_DATABASE_URL이 PostgreSQL일 때만 돈다."""
import hashlib
from datetime import datetime

import pytest
from sqlalchemy import URL, create_engine, select, text
from sqlalchemy.orm import Session

from app import transfer as transfer_cli
from app.database import Base, SessionLocal, engine
from app.migrations import ensure_schema
from app.models import Pet, SavedWalk, SavedWalkPhoto, SavedWalkPoint, User, WalkingCourse
from app.seed import seed_all
from app.services.transfer_service import TransferError, transfer
from tests.test_migrations import drop_everything

pytestmark = pytest.mark.skipif(engine.dialect.name != "postgresql", reason="PostgreSQL 대상이 필요하다")
NOW = datetime(2026, 11, 1, 9, 0)
# 이름 칸(30자)에 들어가는 길이로, 따옴표, 이모지, 역슬래시, LIKE 기호, 줄바꿈을 섞었다.
TRICKY = "두부's \"산책\" 🐾 \\ %_ ;--\n탭\t끝"
MEMO = "긴 메모 " * 2000 + "'; DROP TABLE users; --"
PHOTO = bytes(range(256)) * 4


def sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def source(tmp_path):
    """시드와 함께 한글, 특수문자, NULL, JSON, 사진, 지워서 빈 번호가 있는 SQLite DB."""
    path = tmp_path / "pawpath.db"
    sqlite = create_engine(URL.create("sqlite", database=str(path)))
    ensure_schema(sqlite)
    with Session(sqlite) as db:
        seed_all(db)
        users = [User(name=f"보호자{n}", available_windows=[{"start_hour": 7, "end_hour": 9}]) for n in range(3)]
        db.add_all(users)
        db.flush()
        db.delete(users[1])
        owner = users[2]
        db.flush()
        pet = Pet(user_id=owner.id, name=TRICKY, breed="", age_years=3, weight_kg=7.5, size="medium", activity_level="high",
                  personality="active", path_preference="new", heat_sensitivity="low", novelty_reaction="curious",
                  learned_attribute_weights={"그늘": 0.25, "nested": {"list": [1, 2.5, None, True]}})
        db.add(pet)
        walk = SavedWalk(user_id=owner.id, pet_id=None, title=TRICKY, memo=MEMO, source_type="gps", started_at=datetime(2026, 10, 31, 7, 0),
                         ended_at=None, distance_m=1234.5, duration_sec=None, point_count=2, route_hash="a" * 64, preview=[[37.55, 126.91]])
        db.add(walk)
        db.flush()
        db.add_all([
            SavedWalkPoint(walk_id=walk.id, sequence=0, latitude=37.5560001, longitude=126.9105001, recorded_at=datetime(2026, 10, 31, 7, 0, 0, 123456)),
            SavedWalkPoint(walk_id=walk.id, sequence=1, latitude=37.5561, longitude=126.9106, recorded_at=None),
            SavedWalkPhoto(walk_id=walk.id, data=PHOTO, content_type="image/jpeg", size_bytes=len(PHOTO)),
        ])
        db.commit()
    sqlite.dispose()
    return path


@pytest.fixture
def empty_target():
    drop_everything()
    yield engine.url.render_as_string(hide_password=False)
    drop_everything()


def test_everything_is_copied_and_compared_row_by_row(source, empty_target, tmp_path):
    before = sha256(source)
    report = transfer(source, empty_target, tmp_path / "backups", NOW)
    assert sha256(source) == before
    # 백업은 SQLite 온라인 백업이라 바이트까지 같지는 않다. 검증을 마친 사본에만 체크섬이 붙는다.
    assert report.backup.name == "pre-postgres-20261101-090000.db"
    assert report.backup.with_name(report.backup.name + ".sha256").exists()
    assert report.rows["users"] == (3, 3)
    assert report.rows["saved_walk_points"] == (2, 2)
    with SessionLocal() as db:
        assert db.scalars(select(User.id).order_by(User.id)).all() == [1, 2, 4]
        pet = db.scalar(select(Pet).where(Pet.name == TRICKY))
        assert pet.learned_attribute_weights == {"그늘": 0.25, "nested": {"list": [1, 2.5, None, True]}}
        walk = db.scalar(select(SavedWalk))
        assert walk.title == TRICKY and walk.memo == MEMO and walk.duration_sec is None and walk.ended_at is None
        points = db.scalars(select(SavedWalkPoint).order_by(SavedWalkPoint.sequence)).all()
        assert points[0].recorded_at == datetime(2026, 10, 31, 7, 0, 0, 123456) and points[1].recorded_at is None
        assert db.scalar(select(SavedWalkPhoto.data)) == PHOTO
        assert db.scalar(select(WalkingCourse.is_active).limit(1)) is True
        # 옮긴 뒤 새로 만드는 행은 옮긴 번호와 겹치지 않는다.
        db.add(User(name="새 보호자", available_windows=[]))
        db.commit()
        assert db.scalar(select(User.id).where(User.name == "새 보호자")) == 5


def test_target_with_data_is_refused_and_left_alone(source, empty_target, tmp_path):
    ensure_schema(engine)
    with SessionLocal() as db:
        seed_all(db)
    with pytest.raises(TransferError, match="비어 있지 않아요"):
        transfer(source, empty_target, tmp_path / "backups", NOW)
    assert not (tmp_path / "backups").exists()


def test_orphan_rows_stop_the_transfer_and_nothing_is_written(source, empty_target, tmp_path):
    sqlite = create_engine(URL.create("sqlite", database=str(source)))
    with sqlite.begin() as connection:
        # SQLite는 외래 키를 검사하지 않아 주인이 없는 반려동물이 남을 수 있다.
        connection.execute(text("UPDATE pets SET user_id = 999 WHERE id = 1"))
    sqlite.dispose()
    with pytest.raises(TransferError, match=r"pets\.user_id → users: 1행"):
        transfer(source, empty_target, tmp_path / "backups", NOW)
    with SessionLocal() as db:
        assert db.scalar(select(User.id).limit(1)) is None


def test_value_postgres_refuses_is_reported_and_nothing_is_written(source, empty_target, tmp_path):
    sqlite = create_engine(URL.create("sqlite", database=str(source)))
    with sqlite.begin() as connection:
        # SQLite는 글자 수 제한(30자)을 검사하지 않는다.
        connection.execute(text("UPDATE pets SET name = :name WHERE id = 1"), {"name": "가" * 31})
    sqlite.dispose()
    with pytest.raises(TransferError, match="pets: PostgreSQL이 받지 않는 값"):
        transfer(source, empty_target, tmp_path / "backups", NOW)
    with SessionLocal() as db:
        assert db.scalar(select(User.id).limit(1)) is None


def test_old_sqlite_layout_is_upgraded_on_a_copy_before_moving(source, empty_target, tmp_path):
    sqlite = create_engine(URL.create("sqlite", database=str(source)))
    with sqlite.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
        connection.execute(text("DROP TABLE recommendation_events"))
    sqlite.dispose()
    before = sha256(source)
    report = transfer(source, empty_target, tmp_path / "backups", NOW)
    assert sha256(source) == before
    assert report.rows["recommendation_events"] == (None, 0)


def test_cli_prints_the_table_counts(source, empty_target, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        assert transfer_cli.main([str(source)]) == 0
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    output = capsys.readouterr().out
    assert "users" in output and "모든 행을 원본과 하나씩 비교해 같음을 확인했어요." in output
    assert set(Base.metadata.tables) <= {line.split()[0] for line in output.splitlines()[2:] if line.strip()} | {"모든"}
