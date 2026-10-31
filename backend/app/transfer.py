"""SQLite → PostgreSQL 이전 명령. backend 폴더에서 실행한다.

    uv run python -m app.transfer ./pawpath.db

대상은 DATABASE_URL의 PostgreSQL이다. 원본 파일은 바꾸지 않고, 백업 폴더에 pre-postgres-*.db 백업을 먼저 남긴다.
"""
import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.services import backup_service
from app.services.backup_service import BackupError
from app.services.transfer_service import TransferError, transfer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.transfer", description="SQLite DB의 데이터를 빈 PostgreSQL DB(DATABASE_URL)로 옮긴다.")
    parser.add_argument("source", type=Path, help="옮길 SQLite 파일. 예: ./pawpath.db")
    args = parser.parse_args(argv)
    settings = get_settings()
    try:
        report = transfer(args.source, settings.database_url, Path(settings.backup_dir), backup_service.current_time(settings))
    except (TransferError, BackupError) as error:
        print(f"옮기지 못함: {error}", file=sys.stderr)
        return 1
    print(f"원본 백업: {report.backup}")
    print(f"{'테이블':<24}{'원본':>8}{'옮김':>8}")
    for name, (original, moved) in report.rows.items():
        print(f"{name:<24}{'-' if original is None else original:>8}{moved:>8}")
    print("모든 행을 원본과 하나씩 비교해 같음을 확인했어요.")
    if any(original != moved for original, moved in report.rows.values()):
        # 원본 파일의 수와 다른 테이블은 예전 구조를 올리면서 채운 것이다(예: 계정마다 대표 프로필).
        print("원본과 수가 다른 테이블은 예전 구조를 지금 구조로 올리며 채운 행이에요. 비교는 올린 뒤의 사본과 했어요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
