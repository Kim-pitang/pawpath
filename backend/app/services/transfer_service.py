"""SQLite DB의 데이터를 빈 PostgreSQL DB로 옮긴다.

원본 파일은 읽기만 한다. 먼저 검증된 백업을 만들고, 그 백업의 사본을 지금 구조로 올린 뒤 옮긴다.
옮기기, 번호 시퀀스 맞추기, 행 단위 비교가 한 트랜잭션이라 하나라도 실패하면 대상 DB에는 아무것도 남지 않는다.
"""
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from itertools import zip_longest
from pathlib import Path

from sqlalchemy import URL, Connection, Table, and_, create_engine, func, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from app.database import Base, sync_id_sequence
from app.migrations import ensure_schema
from app.services import backup_service

CHUNK_ROWS = 5000


class TransferError(Exception):
    """사용자에게 그대로 보여 줄 수 있는 이전 실패 이유."""


@dataclass(frozen=True)
class TransferReport:
    backup: Path
    # 테이블별 (원본 파일의 행 수, 옮긴 행 수). 원본에 없던 테이블은 None이다.
    rows: dict[str, tuple[int | None, int]]


def _counts(engine: Engine) -> dict[str, int]:
    tables = set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        return {table.name: connection.execute(select(func.count()).select_from(table)).scalar_one() for table in Base.metadata.sorted_tables if table.name in tables}


def _refuse_if_not_empty(target: Engine) -> None:
    filled = {name: count for name, count in _counts(target).items() if count}
    if filled:
        listed = ", ".join(f"{name} {count}" for name, count in filled.items())
        raise TransferError(f"대상 DB가 비어 있지 않아요({listed}). 섞이지 않게 빈 DB로만 옮겨요. docs/POSTGRES.md를 보세요.")


def _orphans(connection: Connection) -> list[str]:
    """부모 행이 없는 외래 키. SQLite는 외래 키를 검사하지 않아 이런 행이 있을 수 있고, PostgreSQL은 이 행을 받지 않는다."""
    found = []
    for table in Base.metadata.sorted_tables:
        for constraint in table.foreign_key_constraints:
            parent = constraint.referred_table
            filled = and_(*(column.isnot(None) for column in constraint.columns))
            has_parent = select(parent).where(and_(*(element.parent == element.column for element in constraint.elements))).exists()
            count = connection.execute(select(func.count()).select_from(table).where(filled, ~has_parent)).scalar_one()
            if count:
                columns = ", ".join(column.name for column in constraint.columns)
                found.append(f"{table.name}.{columns} → {parent.name}: {count}행")
    return found


def _ordered(connection: Connection, table: Table):
    return connection.execution_options(yield_per=CHUNK_ROWS).execute(select(table).order_by(*table.primary_key.columns))


def _copy(reading: Connection, writing: Connection, table: Table) -> None:
    # 값은 모델의 타입을 거쳐 옮긴다. JSON은 문자열이 아니라 값으로, 참거짓은 0과 1이 아니라 boolean으로 들어간다.
    for chunk in _ordered(reading, table).partitions():
        try:
            writing.execute(table.insert(), [row._asdict() for row in chunk])
        except DBAPIError as error:
            # SQLite는 글자 수 제한 등을 검사하지 않아, PostgreSQL이 받지 않는 값이 남아 있을 수 있다.
            reason = str(error.orig).splitlines()[0]
            raise TransferError(f"{table.name}: PostgreSQL이 받지 않는 값이 있어요({reason}). 대상 DB의 변경은 모두 되돌렸어요.") from error
    if "id" in table.c:
        sync_id_sequence(writing, table)


def _compare(reading: Connection, writing: Connection, table: Table) -> int:
    """두 DB의 행을 기본 키 순서로 하나씩 비교한다. 누락, 중복, 값이 바뀐 행이 하나라도 있으면 멈춘다."""
    count = 0
    for source, target in zip_longest(_ordered(reading, table), _ordered(writing, table)):
        if source is None or target is None or tuple(source) != tuple(target):
            key = (source or target)._mapping[table.primary_key.columns[0].name]
            raise TransferError(f"{table.name}: 번호 {key}의 행이 원본과 달라요. 대상 DB의 변경은 모두 되돌렸어요.")
        count += 1
    return count


def transfer(source_path: Path, target_url: str, backup_dir: Path, now: datetime) -> TransferReport:
    source_path = source_path.resolve()
    if not source_path.is_file():
        raise TransferError(f"SQLite DB 파일이 없어요: {source_path}")
    target = create_engine(target_url)
    try:
        if target.dialect.name != "postgresql":
            raise TransferError("대상은 PostgreSQL이어야 해요. DATABASE_URL을 확인하세요.")
        _refuse_if_not_empty(target)
        backup = backup_service.create_backup(source_path, backup_dir, now, kind="pre-postgres")
        work = Path(tempfile.mkdtemp(prefix=".transfer-", dir=backup_dir))
        try:
            copy = work / "source.db"
            shutil.copyfile(backup, copy)
            source = create_engine(URL.create("sqlite", database=str(copy)))
            try:
                original = _counts(source)
                # 예전 구조의 파일이면 서버가 켜질 때와 똑같이 지금 구조로 올린다. 사본에서만 일어난다.
                ensure_schema(source)
                ensure_schema(target)
                with source.connect() as reading, target.begin() as writing:
                    orphans = _orphans(reading)
                    if orphans:
                        raise TransferError("부모가 없는 행이 있어 옮기지 않았어요. 원본에서 정리한 뒤 다시 실행하세요: " + "; ".join(orphans))
                    for table in Base.metadata.sorted_tables:
                        _copy(reading, writing, table)
                    moved = {table.name: _compare(reading, writing, table) for table in Base.metadata.sorted_tables}
            finally:
                source.dispose()
        finally:
            shutil.rmtree(work, ignore_errors=True)
    finally:
        target.dispose()
    return TransferReport(backup, {name: (original.get(name), count) for name, count in moved.items()})
