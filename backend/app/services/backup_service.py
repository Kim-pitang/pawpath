"""SQLite DB 백업, 검증, 복구. 표준 라이브러리 sqlite3의 온라인 백업만 쓴다. 정책은 docs/BACKUP.md에 있다.

온라인 백업은 서버가 돌아가는 중에도 일관된 사본을 만들고, 복구도 같은 방법으로 파일을 바꾸지 않고 내용만
트랜잭션으로 덮어쓴다. 그래서 복구 중에 멈춰도 DB가 깨지지 않고, 서버의 열린 연결도 새 내용을 읽는다.
"""
import hashlib
import logging
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import URL, Engine, create_engine, delete, update
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import Settings
from app import migrations
from app.migrations import ensure_schema
from app.models import AuthSession, CommunityTrail, OAuthState, SavedWalk
from app.services import account_service

BACKUP_NAME = re.compile(r"^(pawpath|pre-restore|pre-migration)-(\d{8}-\d{6})\.db$")
# 이 테이블이 없으면 PawPath DB가 아니다. 나중에 더한 테이블은 복구할 때 자동으로 만든다.
REQUIRED_TABLES = {"users", "pets", "walking_courses", "walk_histories", "recommendations"}
BUSY_SECONDS = 30
STALE_TEMP = timedelta(days=1)
# DB와 함께 다뤄야 하는 SQLite 보조 파일.
SIDECARS = ("-journal", "-wal", "-shm")
logger = logging.getLogger(__name__)


class BackupError(Exception):
    """사용자에게 그대로 보여 줄 수 있는 백업, 복구 실패 이유."""


@dataclass(frozen=True)
class BackupFile:
    path: Path
    kind: str
    created_at: datetime
    size_bytes: int


@dataclass(frozen=True)
class VerifiedBackup:
    path: Path
    checksum_checked: bool
    rows: dict[str, int]


@dataclass(frozen=True)
class MigrationReport:
    backup: Path | None
    added_columns: list[str]
    before: dict[str, int]
    after: dict[str, int]


@dataclass(frozen=True)
class RestoreReport:
    safety_copy: Path | None
    accounts_removed: int
    ledger_found: bool
    sessions_cleared: int
    shares_closed: int
    rows: dict[str, int]


def sqlite_path(database_url: str) -> Path | None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).resolve()


def current_time(settings: Settings) -> datetime:
    """파일 이름에 쓰는 시각. now_local과 달리 초까지 남겨 같은 분의 백업이 겹치지 않게 한다."""
    return datetime.now(ZoneInfo(settings.service_timezone)).replace(tzinfo=None, microsecond=0)


def _open_readonly(path: Path) -> sqlite3.Connection:
    # as_uri()는 절대 경로만 받는다. backup_dir 기본값(./backups)처럼 상대 경로도 들어온다.
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=BUSY_SECONDS)


def _copy_database(source: Path, target: Path) -> None:
    with closing(sqlite3.connect(source, timeout=BUSY_SECONDS)) as origin, closing(sqlite3.connect(target, timeout=BUSY_SECONDS)) as destination:
        origin.backup(destination)


def _inspect(path: Path) -> dict[str, int]:
    """깨진 파일이나 PawPath DB가 아닌 파일을 거부하고, 주요 테이블의 행 수를 돌려준다."""
    try:
        with closing(_open_readonly(path)) as connection:
            verdict = connection.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            missing = REQUIRED_TABLES - tables
            if verdict == "ok" and not missing:
                names = ("users", "profiles", "pets", "walk_histories", "saved_walks", "saved_walk_photos")
                return {name: connection.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in names if name in tables}
    except sqlite3.DatabaseError as error:
        raise BackupError(f"{path.name}: 읽을 수 없는 파일이에요 ({error})") from error
    if verdict != "ok":
        raise BackupError(f"{path.name}: 손상된 DB예요 ({verdict})")
    raise BackupError(f"{path.name}: PawPath DB가 아니에요. 없는 테이블: {', '.join(sorted(missing))}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _checksum_path(path: Path) -> Path:
    return path.with_name(path.name + ".sha256")


def _write_checksum(data_path: Path, name: str) -> None:
    """`shasum -c`로도 확인할 수 있는 형식으로 쓴다."""
    target = _checksum_path(data_path.with_name(name))
    target.write_text(f"{_sha256(data_path)}  {name}\n", encoding="utf-8")
    target.chmod(0o600)


def _prepare_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)


def create_backup(db_path: Path, directory: Path, now: datetime, kind: str = "pawpath") -> Path:
    """검증까지 끝낸 사본만 백업 이름을 받는다. 중간에 멈추면 임시 파일만 남는다."""
    if not db_path.exists():
        raise BackupError(f"DB 파일이 없어요: {db_path}")
    _prepare_directory(directory)
    final = directory / f"{kind}-{now:%Y%m%d-%H%M%S}.db"
    temp = directory / f".{final.name}.tmp"
    temp.unlink(missing_ok=True)
    # 비밀번호 해시, 경로, 사진이 들어 있어 주인만 읽게 한다.
    temp.touch(mode=0o600)
    try:
        _copy_database(db_path, temp)
        _inspect(temp)
        _write_checksum(temp, final.name)
        os.replace(temp, final)
    except sqlite3.DatabaseError as error:
        temp.unlink(missing_ok=True)
        raise BackupError(f"{db_path.name}: 읽을 수 없는 파일이에요 ({error})") from error
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return final


def list_backups(directory: Path) -> list[BackupFile]:
    """오래된 순서로 돌려준다."""
    if not directory.is_dir():
        return []
    found = []
    for path in directory.iterdir():
        match = BACKUP_NAME.match(path.name)
        if match:
            found.append(BackupFile(path, match[1], datetime.strptime(match[2], "%Y%m%d-%H%M%S"), path.stat().st_size))
    return sorted(found, key=lambda item: item.created_at)


def latest_backup(directory: Path) -> BackupFile | None:
    backups = [item for item in list_backups(directory) if item.kind == "pawpath"]
    return backups[-1] if backups else None


def prune_backups(directory: Path, retention_days: int, now: datetime) -> list[Path]:
    """보존 기간이 지난 백업과 중단되어 남은 임시 파일을 지운다. 탈퇴 기록은 지우지 않는다."""
    removed = []
    cutoff = now - timedelta(days=retention_days)
    for backup in list_backups(directory):
        if backup.created_at <= cutoff:
            backup.path.unlink()
            _checksum_path(backup.path).unlink(missing_ok=True)
            for suffix in SIDECARS:
                backup.path.with_name(backup.path.name + suffix).unlink(missing_ok=True)
            removed.append(backup.path)
    if directory.is_dir():
        for temp in directory.glob(".*.tmp"):
            if datetime.fromtimestamp(temp.stat().st_mtime) <= datetime.now() - STALE_TEMP:
                temp.unlink()
    return removed


def run_scheduled(settings: Settings, now: datetime | None = None) -> Path | None:
    """때가 되었으면 백업하고 오래된 백업을 지운다. 백업에 실패하면 예외가 나므로 지우는 단계까지 가지 않는다."""
    db_path = sqlite_path(settings.database_url)
    if db_path is None:
        logger.warning("SQLite가 아니라 자동 백업을 하지 않음. docs/BACKUP.md를 참고해 DB 도구로 백업하세요.")
        return None
    now = now or current_time(settings)
    directory = Path(settings.backup_dir)
    latest = latest_backup(directory)
    created = None
    if latest is None or now - latest.created_at >= timedelta(hours=settings.backup_interval_hours):
        created = create_backup(db_path, directory, now)
    prune_backups(directory, settings.backup_retention_days, now)
    return created


def migrate(engine: Engine, settings: Settings, now: datetime | None = None, force_backup: bool = False) -> MigrationReport:
    """DB 구조를 올린다. 바꿀 것이 있으면 먼저 백업하고, 끝난 뒤 행 수가 줄어든 테이블이 없는지 확인한다.

    프로필 잇기는 한 트랜잭션이라 실패하면 채우던 내용이 모두 되돌아간다. 먼저 더한 빈 컬럼은 남지만 데이터에
    영향이 없고, 다시 실행하면 이어서 진행한다. 백업은 그래도 문제가 남았을 때 restore로 쓴다.
    """
    pending = migrations.needs_migration(engine)
    before = migrations.row_counts(engine)
    db_path = sqlite_path(settings.database_url)
    backup = None
    if pending and (force_backup or settings.backup_enabled) and db_path is not None and db_path.exists():
        backup = create_backup(db_path, Path(settings.backup_dir), now or current_time(settings), kind="pre-migration")
    added = ensure_schema(engine)
    after = migrations.row_counts(engine)
    shrunk = [f"{name} {count}→{after.get(name, 0)}" for name, count in before.items() if after.get(name, 0) < count]
    if shrunk:
        hint = f" 백업으로 되돌리세요: uv run python -m app.backup restore {backup.name}" if backup else ""
        raise BackupError(f"마이그레이션 뒤 행 수가 줄었어요: {', '.join(shrunk)}.{hint}")
    return MigrationReport(backup, added, before, after)


def verify_backup(path: Path) -> VerifiedBackup:
    if not path.is_file():
        raise BackupError(f"백업 파일이 없어요: {path}")
    checksum = _checksum_path(path)
    checked = checksum.exists()
    if checked:
        expected = checksum.read_text(encoding="utf-8").split()[0]
        if expected != _sha256(path):
            raise BackupError(f"{path.name}: 체크섬이 달라요. 파일이 바뀌었거나 복사하다 잘렸어요.")
    return VerifiedBackup(path, checked, _inspect(path))


def _prepare_restored(path: Path, directory: Path) -> tuple[int, int, int]:
    """복구할 사본을 지금 쓸 수 있는 상태로 만든다.

    백업 뒤에 일어난 일 중 다시 되살아나면 안 되는 것을 처리한다. 탈퇴한 계정은 다시 지우고, 로그아웃한 세션이
    살아나지 않게 세션을 모두 끝내며, 해제한 공유가 살아나지 않게 공유 링크와 커뮤니티 공개를 모두 비공개로 돌린다.
    """
    engine = create_engine(URL.create("sqlite", database=str(path)))
    try:
        ensure_schema(engine)
        with Session(engine) as db:
            removed = account_service.replay_deletions(db, account_service.read_deletions(directory))
            sessions = db.execute(delete(AuthSession)).rowcount
            db.execute(delete(OAuthState))
            shares = db.execute(
                update(SavedWalk).where(SavedWalk.visibility != "private").values(visibility="private", share_token=None, share_expires_at=None)
            ).rowcount
            shares += db.execute(update(CommunityTrail).where(CommunityTrail.visibility != "private").values(visibility="private")).rowcount
            db.commit()
    finally:
        engine.dispose()
    return removed, sessions, shares


def _keep_current(db_path: Path, directory: Path, now: datetime) -> Path | None:
    """복구 전 DB를 남겨 둔다. 읽을 수 없는 파일은 복사 대신 그대로 옮긴다."""
    if not db_path.exists():
        return None
    _prepare_directory(directory)
    target = directory / f"pre-restore-{now:%Y%m%d-%H%M%S}.db"
    target.touch(mode=0o600)
    try:
        _copy_database(db_path, target)
        _inspect(target)
        _write_checksum(target, target.name)
    except (sqlite3.DatabaseError, BackupError):
        shutil.move(db_path, target)
        target.chmod(0o600)
        for suffix in SIDECARS:
            sidecar = db_path.with_name(db_path.name + suffix)
            if sidecar.exists():
                # 남겨 두면 SQLite가 새 DB에 옛 저널을 적용해 복구한 DB를 망가뜨린다.
                shutil.move(sidecar, target.with_name(target.name + suffix))
    return target


def restore_backup(backup: Path, db_path: Path, directory: Path, now: datetime) -> RestoreReport:
    """백업으로 DB를 되돌린다. 백업 파일은 바꾸지 않고, 준비를 마친 사본으로만 지금 DB를 덮어쓴다."""
    verify_backup(backup)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_found = (directory / account_service.LEDGER_NAME).exists()
    work = Path(tempfile.mkdtemp(prefix=".restore-", dir=db_path.parent))
    try:
        prepared = work / "restored.db"
        _copy_database(backup, prepared)
        removed, sessions, shares = _prepare_restored(prepared, directory)
        rows = _inspect(prepared)
        safety_copy = _keep_current(db_path, directory, now)
        _copy_database(prepared, db_path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return RestoreReport(safety_copy, removed, ledger_found, sessions, shares, rows)
