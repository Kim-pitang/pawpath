"""백업 명령. backend 폴더에서 실행한다: uv run python -m app.backup {create,list,verify,restore,migrate}"""
import argparse
import sqlite3
import sys
from pathlib import Path

from app.config import Settings, get_settings
from app.services import backup_service
from app.services.backup_service import BackupError


def _database(settings: Settings) -> Path:
    path = backup_service.sqlite_path(settings.database_url)
    if path is None:
        raise BackupError("SQLite가 아니에요. PostgreSQL은 pg_dump로 백업하세요(docs/BACKUP.md).")
    return path


def _rows(rows: dict[str, int]) -> str:
    return ", ".join(f"{name} {count}" for name, count in rows.items())


def _create(settings: Settings, _: argparse.Namespace) -> None:
    now = backup_service.current_time(settings)
    directory = Path(settings.backup_dir)
    print(f"백업함: {backup_service.create_backup(_database(settings), directory, now)}")
    for path in backup_service.prune_backups(directory, settings.backup_retention_days, now):
        print(f"보존 기간이 지나 지움: {path.name}")


def _list(settings: Settings, _: argparse.Namespace) -> None:
    backups = backup_service.list_backups(Path(settings.backup_dir))
    if not backups:
        print(f"백업이 없어요: {settings.backup_dir}")
    for item in backups:
        print(f"{item.created_at}  {item.size_bytes / (1024 * 1024):8.1f} MB  {item.path.name}")


def _resolve(settings: Settings, name: str) -> Path:
    directory = Path(settings.backup_dir)
    if name == "latest":
        latest = backup_service.latest_backup(directory)
        if latest is None:
            raise BackupError(f"백업이 없어요: {directory}")
        return latest.path
    path = Path(name)
    return path if path.exists() or path.parent != Path(".") else directory / name


def _verify(settings: Settings, args: argparse.Namespace) -> None:
    result = backup_service.verify_backup(_resolve(settings, args.file))
    checksum = "체크섬 일치" if result.checksum_checked else "체크섬 파일 없음"
    print(f"정상: {result.path.name} ({checksum}, {_rows(result.rows)})")


def _restore(settings: Settings, args: argparse.Namespace) -> None:
    backup = _resolve(settings, args.file)
    database = _database(settings)
    result = backup_service.verify_backup(backup)
    print(f"복구할 백업: {result.path.name} ({_rows(result.rows)})")
    print(f"덮어쓸 DB: {database}")
    print("백업 뒤의 변경은 사라져요. 모든 보호자가 다시 로그인해야 하고, 공유한 산책길은 비공개로 돌아가요.")
    if not args.yes and input('계속하려면 "복구"를 입력하세요: ').strip() != "복구":
        raise BackupError("복구를 취소했어요.")
    report = backup_service.restore_backup(backup, database, Path(settings.backup_dir), backup_service.current_time(settings))
    print(f"복구함: {_rows(report.rows)}")
    print(f"복구 전 DB: {report.safety_copy or '없었음'}")
    print(f"탈퇴 기록으로 다시 지운 계정: {report.accounts_removed}" + ("" if report.ledger_found else " (탈퇴 기록 파일 없음)"))
    print(f"끝낸 세션: {report.sessions_cleared}, 비공개로 돌린 산책길: {report.shares_closed}")


def _migrate(settings: Settings, _: argparse.Namespace) -> None:
    from app.database import engine

    report = backup_service.migrate(engine, settings, force_backup=True)
    print(f"마이그레이션 전 백업: {report.backup or '바꿀 것이 없어 만들지 않음'}")
    print(f"더한 컬럼: {', '.join(report.added_columns) or '없음'}")
    for name, after in report.after.items():
        before = report.before.get(name, 0)
        print(f"  {name:20} {before:>7} → {after:>7}" + ("" if before == after else "  (늘어남)"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.backup", description="PawPath DB 백업과 복구")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("create", help="지금 백업하고 보존 기간이 지난 백업을 지운다").set_defaults(run=_create)
    commands.add_parser("list", help="백업 목록").set_defaults(run=_list)
    verify = commands.add_parser("verify", help="백업이 복구할 수 있는 상태인지 확인한다")
    verify.add_argument("file", nargs="?", default="latest", help="백업 파일 이름이나 경로. 기본은 가장 최근 백업")
    verify.set_defaults(run=_verify)
    restore = commands.add_parser("restore", help="백업으로 DB를 되돌린다")
    restore.add_argument("file", help='백업 파일 이름이나 경로, 또는 "latest"')
    restore.add_argument("--yes", action="store_true", help="확인을 묻지 않는다")
    restore.set_defaults(run=_restore)
    commands.add_parser("migrate", help="백업한 뒤 DB 구조를 올리고 전후 행 수를 비교한다").set_defaults(run=_migrate)
    args = parser.parse_args(argv)
    try:
        args.run(get_settings(), args)
    except (BackupError, OSError, sqlite3.Error) as error:
        print(f"실패: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
