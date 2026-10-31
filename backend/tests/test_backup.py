"""백업, 보존 기간, 복구. 실제 파일과 실제 SQLite로 확인한다."""
import asyncio
import os
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import URL, create_engine, select
from sqlalchemy.orm import Session

from app import backup as backup_cli
from app import main
from app.config import Settings, get_settings
from app.database import Base
from app.models import (
    AuthSession,
    OAuthState,
    Pet,
    SavedWalk,
    SavedWalkPhoto,
    SavedWalkPoint,
    User,
)
from app.seed import new_user_defaults
from app.services import account_service, backup_service
from app.services.backup_service import BackupError

NOW = datetime(2026, 10, 31, 3, 0, 0)
PET = dict(
    breed="말티즈",
    age_years=5,
    weight_kg=4.2,
    size="small",
    activity_level="medium",
    personality="timid",
    path_preference="familiar",
    heat_sensitivity="medium",
    novelty_reaction="anxious",
)


@pytest.fixture
def live(tmp_path) -> Path:
    path = tmp_path / "data" / "pawpath.db"
    path.parent.mkdir()
    engine = create_engine(URL.create("sqlite", database=str(path)))
    Base.metadata.create_all(engine)
    engine.dispose()
    return path


@pytest.fixture
def directory(tmp_path) -> Path:
    return tmp_path / "backups"


def open_db(path: Path) -> Session:
    return Session(create_engine(URL.create("sqlite", database=str(path))), expire_on_commit=False)


def add_user(path: Path, login_id: str, created_at: datetime = datetime(2026, 10, 1), walk_visibility: str | None = None) -> int:
    with open_db(path) as db:
        user = User(name=login_id, login_id=login_id, password_hash="x", created_at=created_at, **new_user_defaults())
        db.add(user)
        db.flush()
        db.add(Pet(user_id=user.id, name=f"{login_id}의 개", **PET))
        db.add(AuthSession(user_id=user.id, token_hash=f"hash-{login_id}", created_at=NOW, expires_at=NOW + timedelta(days=30)))
        if walk_visibility:
            walk = SavedWalk(
                user_id=user.id,
                title=f"{login_id}의 길",
                memo="",
                source_type="recorded",
                started_at=NOW,
                distance_m=100,
                point_count=1,
                visibility=walk_visibility,
                share_token=f"token-{login_id}" if walk_visibility != "private" else None,
                route_hash="h",
                preview=[],
            )
            walk.points = [SavedWalkPoint(sequence=0, segment=0, latitude=37.5, longitude=127.0)]
            walk.photos = [SavedWalkPhoto(content_type="image/jpeg", data=b"photo-bytes", size_bytes=11)]
            db.add(walk)
        db.commit()
        return user.id


def logins(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as connection:
        return sorted(row[0] for row in connection.execute("SELECT login_id FROM users"))


def settings_for(live: Path, directory: Path, **overrides) -> Settings:
    return Settings(_env_file=None, database_url=f"sqlite:///{live}", backup_dir=str(directory), **overrides)


# ---------- 백업 만들기
def test_backup_is_a_verified_private_copy(live, directory):
    add_user(live, "alice")
    path = backup_service.create_backup(live, directory, NOW)
    assert path.name == "pawpath-20261031-030000.db"
    assert logins(path) == ["alice"]
    # 비밀번호 해시와 경로가 들어 있어 주인만 읽는다.
    assert path.stat().st_mode & 0o077 == 0
    assert directory.stat().st_mode & 0o077 == 0
    checksum = path.with_name(path.name + ".sha256")
    assert checksum.stat().st_mode & 0o077 == 0
    assert checksum.read_text().split() == [backup_service._sha256(path), path.name]
    result = backup_service.verify_backup(path)
    assert result.checksum_checked and result.rows["users"] == 1
    assert not list(directory.glob(".*.tmp"))


def test_backup_is_consistent_while_a_write_is_in_progress(live, directory):
    """서버가 쓰는 중이어도 커밋된 내용만 들어가고, 백업이 쓰기를 깨지 않는다."""
    add_user(live, "alice")
    with closing(sqlite3.connect(live)) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO users (name, available_windows, preferred_duration_min, walks_per_day, login_id, created_at, updated_at) VALUES ('x', '[]', 40, 1, 'uncommitted', '2026-10-01', '2026-10-01')")
        path = backup_service.create_backup(live, directory, NOW)
        writer.commit()
    assert logins(path) == ["alice"]
    assert logins(live) == ["alice", "uncommitted"]


def test_backup_does_not_touch_the_original(live, directory):
    add_user(live, "alice")
    before = live.read_bytes()
    backup_service.create_backup(live, directory, NOW)
    assert live.read_bytes() == before


def test_missing_database_is_an_error(tmp_path, directory):
    with pytest.raises(BackupError, match="DB 파일이 없어요"):
        backup_service.create_backup(tmp_path / "nothing.db", directory, NOW)
    assert not (tmp_path / "nothing.db").exists()


def test_corrupt_database_does_not_become_a_backup(tmp_path, directory):
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"this is not sqlite" * 100)
    with pytest.raises(BackupError, match="읽을 수 없는"):
        backup_service.create_backup(broken, directory, NOW)
    assert backup_service.list_backups(directory) == []
    assert not list(directory.glob(".*.tmp"))


def test_only_sqlite_is_backed_up():
    assert backup_service.sqlite_path("postgresql+psycopg://user:pw@localhost/pawpath") is None
    assert backup_service.sqlite_path("sqlite:///:memory:") is None
    assert backup_service.sqlite_path("sqlite:///./pawpath.db") == Path("pawpath.db").resolve()


# ---------- 검증
def test_verify_catches_a_changed_file(live, directory):
    path = backup_service.create_backup(live, directory, NOW)
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    path.write_bytes(data)
    with pytest.raises(BackupError, match="체크섬"):
        backup_service.verify_backup(path)


def test_verify_catches_a_truncated_file_without_a_checksum(live, directory):
    add_user(live, "alice")
    path = backup_service.create_backup(live, directory, NOW)
    path.with_name(path.name + ".sha256").unlink()
    path.write_bytes(path.read_bytes()[: 4096 + 100])
    with pytest.raises(BackupError):
        backup_service.verify_backup(path)


def test_verify_accepts_a_good_copy_without_a_checksum(live, directory):
    path = backup_service.create_backup(live, directory, NOW)
    path.with_name(path.name + ".sha256").unlink()
    assert backup_service.verify_backup(path).checksum_checked is False


def test_verify_refuses_files_that_are_not_pawpath(tmp_path):
    other = tmp_path / "other.db"
    with closing(sqlite3.connect(other)) as connection:
        connection.execute("CREATE TABLE notes (id INTEGER)")
        connection.commit()
    with pytest.raises(BackupError, match="PawPath DB가 아니에요"):
        backup_service.verify_backup(other)
    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(b"not a database at all" * 100)
    with pytest.raises(BackupError, match="읽을 수 없는"):
        backup_service.verify_backup(garbage)
    with pytest.raises(BackupError, match="백업 파일이 없어요"):
        backup_service.verify_backup(tmp_path / "missing.db")


# ---------- 일정과 보존 기간
def test_schedule_makes_a_backup_only_when_due(live, directory):
    settings = settings_for(live, directory, backup_interval_hours=24)
    first = backup_service.run_scheduled(settings, NOW)
    assert first is not None
    assert backup_service.run_scheduled(settings, NOW + timedelta(hours=23, minutes=59)) is None
    assert backup_service.run_scheduled(settings, NOW + timedelta(hours=24)) is not None
    assert len(backup_service.list_backups(directory)) == 2


def test_retention_removes_only_expired_backups(live, directory):
    settings = settings_for(live, directory, backup_interval_hours=24, backup_retention_days=14)
    for days in (20, 14, 13, 1):
        backup_service.create_backup(live, directory, NOW - timedelta(days=days))
    account_service.record_deletion(directory, 5, NOW, NOW)
    (directory / "my-note.txt").write_text("남겨 두어야 함")
    backup_service.run_scheduled(settings, NOW)
    names = [item.path.name for item in backup_service.list_backups(directory)]
    assert names == ["pawpath-20261018-030000.db", "pawpath-20261030-030000.db", "pawpath-20261031-030000.db"]
    assert not (directory / "pawpath-20261011-030000.db.sha256").exists()
    # 탈퇴 기록은 복구 때 필요하고 개인정보가 없어 지우지 않는다. 모르는 파일도 건드리지 않는다.
    assert account_service.read_deletions(directory)
    assert (directory / "my-note.txt").exists()


def test_failed_backup_never_prunes_the_old_ones(live, directory):
    """백업이 계속 실패하면 보존 기간이 지나도 남은 백업을 지키는 쪽을 택한다."""
    old = backup_service.create_backup(live, directory, NOW - timedelta(days=30))
    live.unlink()
    with pytest.raises(BackupError):
        backup_service.run_scheduled(settings_for(live, directory), NOW)
    assert old.exists()


def test_leftover_temp_files_are_cleaned_up(live, directory):
    backup_service.create_backup(live, directory, NOW)
    temp = directory / ".pawpath-20260101-000000.db.tmp"
    temp.write_bytes(b"personal data from an interrupted backup")
    old = (datetime.now() - timedelta(days=2)).timestamp()
    os.utime(temp, (old, old))
    fresh = directory / ".pawpath-20261031-000000.db.tmp"
    fresh.write_bytes(b"backup in progress")
    backup_service.prune_backups(directory, 14, NOW)
    assert not temp.exists()
    assert fresh.exists()


def test_non_sqlite_database_is_skipped_with_a_warning(directory, caplog):
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://u:p@localhost/x", backup_dir=str(directory))
    assert backup_service.run_scheduled(settings, NOW) is None
    assert "SQLite가 아니라" in caplog.text
    assert not directory.exists()


# ---------- 복구
def test_restore_brings_back_lost_data_and_keeps_the_current_db(live, directory):
    add_user(live, "alice")
    backup = backup_service.create_backup(live, directory, NOW)
    add_user(live, "added-later")
    report = backup_service.restore_backup(backup, live, directory, NOW + timedelta(hours=1))
    assert logins(live) == ["alice"]
    assert report.rows["users"] == 1
    # 잘못 복구해도 되돌릴 수 있게 복구 전 DB를 남긴다.
    assert report.safety_copy.name == "pre-restore-20261031-040000.db"
    assert logins(report.safety_copy) == ["added-later", "alice"]
    assert report.safety_copy.stat().st_mode & 0o077 == 0
    assert backup_service.verify_backup(report.safety_copy).checksum_checked


def test_restore_leaves_the_backup_file_unchanged(live, directory):
    add_user(live, "alice", walk_visibility="link")
    backup = backup_service.create_backup(live, directory, NOW)
    before = backup.read_bytes()
    backup_service.restore_backup(backup, live, directory, NOW + timedelta(hours=1))
    assert backup.read_bytes() == before
    assert not list(live.parent.glob(".restore-*"))


def test_restored_account_of_someone_who_left_stays_deleted(live, directory):
    keeper = add_user(live, "keeper")
    leaver = add_user(live, "leaver", walk_visibility="public")
    backup = backup_service.create_backup(live, directory, NOW)
    with open_db(live) as db:
        created_at = db.get(User, leaver).created_at
        account_service.delete_user_data(db, leaver)
        db.commit()
    account_service.record_deletion(directory, leaver, created_at, NOW + timedelta(minutes=1))

    report = backup_service.restore_backup(backup, live, directory, NOW + timedelta(hours=1))
    assert report.accounts_removed == 1
    assert report.ledger_found
    assert logins(live) == ["keeper"]
    with closing(sqlite3.connect(live)) as connection:
        for table, column in (("pets", "user_id"), ("saved_walks", "user_id"), ("auth_sessions", "user_id")):
            assert connection.execute(f"SELECT count(*) FROM {table} WHERE {column} = ?", (leaver,)).fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM saved_walk_points").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM saved_walk_photos").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM pets WHERE user_id = ?", (keeper,)).fetchone()[0] == 1
    # 다시 지운 내용이 파일의 빈 공간에도 남지 않는다.
    assert b"photo-bytes" not in live.read_bytes()
    assert b"leaver" not in live.read_bytes()


def test_new_account_with_a_reused_number_is_not_deleted(live, directory):
    """SQLite는 마지막 번호를 다시 쓴다. 탈퇴 기록의 번호가 같아도 가입 시각이 다르면 다른 사람이다."""
    leaver = add_user(live, "leaver", created_at=datetime(2026, 9, 1))
    with open_db(live) as db:
        account_service.delete_user_data(db, leaver)
        db.commit()
    account_service.record_deletion(directory, leaver, datetime(2026, 9, 1), NOW)
    newcomer = add_user(live, "newcomer", created_at=datetime(2026, 10, 15))
    assert newcomer == leaver
    backup = backup_service.create_backup(live, directory, NOW)
    report = backup_service.restore_backup(backup, live, directory, NOW + timedelta(hours=1))
    assert report.accounts_removed == 0
    assert logins(live) == ["newcomer"]


def test_restore_ends_all_sessions(live, directory):
    """백업 뒤에 로그아웃한 세션이 복구로 다시 열리면 안 된다."""
    add_user(live, "alice")
    with open_db(live) as db:
        db.add(OAuthState(state_hash="h", nonce="n", code_verifier="v", next_path="/", expires_at=NOW + timedelta(minutes=5)))
        db.commit()
    backup = backup_service.create_backup(live, directory, NOW)
    report = backup_service.restore_backup(backup, live, directory, NOW + timedelta(hours=1))
    assert report.sessions_cleared == 1
    with closing(sqlite3.connect(live)) as connection:
        assert connection.execute("SELECT count(*) FROM auth_sessions").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM oauth_states").fetchone()[0] == 0


def test_restore_closes_shares_because_they_may_have_been_revoked(live, directory):
    """백업 뒤에 해제한 공유 링크를 구분할 수 없으므로 모두 닫는다. 위치 정보라 닫는 쪽을 택한다."""
    add_user(live, "linker", walk_visibility="link")
    add_user(live, "publisher", walk_visibility="public")
    add_user(live, "private", walk_visibility="private")
    backup = backup_service.create_backup(live, directory, NOW)
    report = backup_service.restore_backup(backup, live, directory, NOW + timedelta(hours=1))
    assert report.shares_closed == 2
    with closing(sqlite3.connect(live)) as connection:
        assert connection.execute("SELECT DISTINCT visibility, share_token, share_expires_at FROM saved_walks").fetchall() == [("private", None, None)]


def test_restore_replaces_a_corrupt_database_and_keeps_it_aside(live, directory):
    add_user(live, "alice")
    backup = backup_service.create_backup(live, directory, NOW)
    live.write_bytes(b"corrupted by a disk failure" * 1000)
    journal = live.with_name(live.name + "-journal")
    journal.write_bytes(b"stale journal that would break the restored database")
    report = backup_service.restore_backup(backup, live, directory, NOW + timedelta(hours=1))
    assert logins(live) == ["alice"]
    assert not journal.exists()
    assert report.safety_copy.read_bytes().startswith(b"corrupted by a disk failure")
    with closing(sqlite3.connect(live)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_restore_works_after_the_database_is_lost(live, directory):
    add_user(live, "alice")
    backup = backup_service.create_backup(live, directory, NOW)
    shutil.rmtree(live.parent)
    report = backup_service.restore_backup(backup, live, directory, NOW + timedelta(hours=1))
    assert logins(live) == ["alice"]
    assert report.safety_copy is None


def test_bad_backup_never_touches_the_current_database(live, directory):
    add_user(live, "alice")
    backup = backup_service.create_backup(live, directory, NOW)
    add_user(live, "still-here")
    backup.write_bytes(b"damaged" * 100)
    before = live.read_bytes()
    with pytest.raises(BackupError):
        backup_service.restore_backup(backup, live, directory, NOW + timedelta(hours=1))
    assert live.read_bytes() == before
    assert not list(directory.glob("pre-restore-*"))


def test_old_backup_is_upgraded_to_the_current_schema(live, directory, tmp_path):
    """새 컬럼과 테이블을 더하기 전의 백업도 복구되고, 서버가 바로 쓸 수 있다."""
    add_user(live, "alice")
    old = tmp_path / "old.db"
    backup_service._copy_database(live, old)
    with closing(sqlite3.connect(old)) as connection:
        connection.execute("ALTER TABLE auth_sessions DROP COLUMN last_seen_at")
        connection.execute("ALTER TABLE auth_sessions DROP COLUMN reauthenticated_at")
        connection.execute("ALTER TABLE oauth_states DROP COLUMN reauth_user_id")
        connection.execute("DROP TABLE saved_walk_photos")
        connection.commit()
    backup_service.restore_backup(old, live, directory, NOW)
    with open_db(live) as db:
        assert db.scalars(select(AuthSession)).all() == []
        assert db.scalars(select(SavedWalkPhoto)).all() == []
        assert db.scalar(select(User.login_id)) == "alice"


def test_open_server_connection_reads_the_restored_data(live, directory):
    """서버를 켠 채 복구해도 열린 연결이 깨지지 않고 새 내용을 읽는다."""
    add_user(live, "alice")
    backup = backup_service.create_backup(live, directory, NOW)
    add_user(live, "added-later")
    engine = create_engine(URL.create("sqlite", database=str(live)))
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM users").scalar() == 2
        connection.rollback()
        backup_service.restore_backup(backup, live, directory, NOW + timedelta(hours=1))
        assert connection.exec_driver_sql("SELECT login_id FROM users").scalars().all() == ["alice"]
        connection.rollback()
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE users SET name = 'after restore'")
    engine.dispose()
    with closing(sqlite3.connect(live)) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_ledger_with_a_torn_last_line_is_still_read(directory, caplog):
    account_service.record_deletion(directory, 7, NOW, NOW)
    with (directory / account_service.LEDGER_NAME).open("a", encoding="utf-8") as ledger:
        ledger.write('{"user_id": 8, "user_cre')
    assert [entry["user_id"] for entry in account_service.read_deletions(directory)] == [7]
    assert "읽을 수 없는 줄" in caplog.text


def test_restore_says_when_the_ledger_is_missing(live, directory):
    backup = backup_service.create_backup(live, directory, NOW)
    assert backup_service.restore_backup(backup, live, directory, NOW + timedelta(hours=1)).ledger_found is False


# ---------- 명령
@pytest.fixture
def cli(live, directory, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{live}")
    monkeypatch.setenv("BACKUP_DIR", str(directory))
    get_settings.cache_clear()
    yield live
    monkeypatch.undo()
    get_settings.cache_clear()


def test_cli_create_list_verify_restore(cli, directory, capsys):
    add_user(cli, "alice")
    assert backup_cli.main(["create"]) == 0
    assert "백업함" in capsys.readouterr().out
    assert backup_cli.main(["list"]) == 0
    assert "pawpath-" in capsys.readouterr().out
    assert backup_cli.main(["verify"]) == 0
    assert "체크섬 일치" in capsys.readouterr().out
    add_user(cli, "added-later")
    assert backup_cli.main(["restore", "latest", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "복구 전 DB" in out and "다시 지운 계정: 0" in out and "탈퇴 기록 파일 없음" in out
    assert logins(cli) == ["alice"]


def test_cli_restore_finds_a_file_by_name_and_asks_first(cli, directory, capsys, monkeypatch):
    add_user(cli, "alice")
    path = backup_service.create_backup(cli, directory, NOW)
    add_user(cli, "added-later")
    monkeypatch.setattr("builtins.input", lambda _: "아니요")
    assert backup_cli.main(["restore", path.name]) == 1
    assert "취소" in capsys.readouterr().err
    assert logins(cli) == ["added-later", "alice"]
    monkeypatch.setattr("builtins.input", lambda _: "복구")
    assert backup_cli.main(["restore", path.name]) == 0
    assert logins(cli) == ["alice"]


def test_cli_reports_failures_without_a_traceback(cli, directory, capsys):
    assert backup_cli.main(["verify"]) == 1
    assert "백업이 없어요" in capsys.readouterr().err
    assert backup_cli.main(["restore", "missing.db", "--yes"]) == 1
    assert "백업 파일이 없어요" in capsys.readouterr().err


def test_cli_refuses_postgres(monkeypatch, capsys, directory):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/x")
    monkeypatch.setenv("BACKUP_DIR", str(directory))
    get_settings.cache_clear()
    try:
        assert backup_cli.main(["create"]) == 1
        assert "pg_dump" in capsys.readouterr().err
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


# ---------- 서버의 자동 백업
def test_server_makes_a_backup_on_start_and_keeps_serving(tmp_path, monkeypatch):
    """꺼져 있던 동안 놓친 백업은 켜자마자 만든다. 응답을 막지 않는다."""
    live_path = tmp_path / "server.db"
    engine = create_engine(URL.create("sqlite", database=str(live_path)))
    Base.metadata.create_all(engine)
    engine.dispose()
    directory = tmp_path / "server-backups"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{live_path}")
    monkeypatch.setenv("BACKUP_DIR", str(directory))
    monkeypatch.setenv("BACKUP_ENABLED", "true")
    get_settings.cache_clear()

    async def scenario():
        task = asyncio.create_task(main.backup_loop())
        for _ in range(100):
            await asyncio.sleep(0.02)
            if backup_service.latest_backup(directory):
                break
        task.cancel()

    try:
        asyncio.run(scenario())
        assert backup_service.latest_backup(directory) is not None
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_backup_failure_does_not_stop_the_server_loop(monkeypatch, caplog):
    calls = []

    def fail(_settings):
        calls.append(1)
        raise OSError("disk full")

    monkeypatch.setattr(backup_service, "run_scheduled", fail)
    monkeypatch.setattr(main, "BACKUP_CHECK_SECONDS", 0.01)

    async def scenario():
        task = asyncio.create_task(main.backup_loop())
        await asyncio.sleep(0.1)
        task.cancel()

    asyncio.run(scenario())
    assert len(calls) >= 2
    assert "자동 백업 실패" in caplog.text
