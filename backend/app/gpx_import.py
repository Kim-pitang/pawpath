"""GPX 코스 일괄 적재 도구(관리자용).

    uv run python -m app.gpx_import <GPX 폴더> [--measure] [--apply] [--report 결과.json]
    uv run python -m app.gpx_import --deactivate gpx-강남구_양재천
    uv run python -m app.gpx_import --activate gpx-강남구_양재천

폴더 바로 아래의 *.gpx만 읽고 원본 파일은 고치지 않는다. 결과는 app/data/courses_gpx.json에 쓰며,
서버가 시작할 때 시드 코스와 함께 코드 기준으로 넣거나 갱신하므로 다시 실행해도 중복되지 않는다.
--apply를 주면 서버를 다시 시작하지 않아도 지금 DB에 바로 반영한다.
--measure를 주면 코스마다 Overpass를 한 번 불러 주변 환경을 측정한다. 실패한 코스는 '확인 불가'로 남긴다.
"""
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal, engine
from app.models import WalkingCourse
from app.services import backup_service, environment_service
from app.services import gpx_course_service as service

OUTPUT = Path(__file__).parent / "data" / "courses_gpx.json"
# 공개 Overpass 서버에 몰아서 요청하지 않도록 코스 사이에 쉰다.
MEASURE_INTERVAL_SECONDS = 5.0


def process(folder: Path, measure: bool, previous: dict[str, dict]) -> tuple[list[service.GpxCourse], list[dict]]:
    files = sorted(path for path in folder.glob("*.gpx") if path.is_file() and not path.name.startswith("."))
    manifest = service.read_manifest(folder)
    results = [service.analyze(path.name, path.read_bytes()) for path in files]
    with SessionLocal() as db:
        service.find_overlaps(results, list(db.scalars(select(WalkingCourse))))

    today = date.today().isoformat()
    rows = []
    for result in results:
        if result.status != "ok":
            continue
        environment, note = None, "주변 환경을 측정하지 않았어요."
        old = previous.get(result.code)
        same_file = bool(old) and old["data_sources"].get("source_sha256") == result.sha256
        if same_file and old.get("environment"):
            # 같은 파일을 다시 적재할 때는 이미 잰 환경값을 버리지 않는다. --measure는 아직 못 잰 코스만 잰다.
            environment, note = old["environment"], old["data_sources"].get("environment")
        elif measure:
            environment, note = service.measure(service.course_route(result), today)
            time.sleep(MEASURE_INTERVAL_SECONDS)
        elif same_file:
            note = old["data_sources"].get("environment_unavailable") or note
        values = service.build_values(result, manifest.get(result.source_file), environment, note)
        rows.append({"code": result.code, **values})
    return results, rows


def summary_line(result: service.GpxCourse, row: dict | None) -> str:
    if result.status != "ok":
        return f"  [{result.status}] {result.source_file}: {result.error}"
    gpx = row["data_sources"]["gpx"]
    cleaning = gpx["cleaning"]
    ele = gpx["elevation"]
    parts = [
        f"{row['area']}",
        f"{gpx['route_type']}",
        f"편도 {gpx['one_way_km']:.2f}km → 코스 {row['distance_km']:.2f}km, 약 {row['duration_min']}분",
        f"좌표 {cleaning['raw_points']}→{gpx['point_count']}",
        f"고도 {'+' + str(ele['gain_m']) + 'm' if ele else '없음'}",
        f"환경 {row['data_sources']['environment_status']}",
    ]
    if gpx["similar_courses"]:
        parts.append("비슷한 코스 " + ", ".join(f"{s['name']} {s['overlap']:.0%}" for s in gpx["similar_courses"]))
    return f"  [ok] {result.source_file}: " + " | ".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GPX 폴더를 추천 후보 코스로 적재한다.")
    parser.add_argument("folder", nargs="?", type=Path)
    parser.add_argument("--measure", action="store_true", help="Overpass로 주변 환경을 측정한다")
    parser.add_argument("--apply", action="store_true", help="지금 DB에도 바로 반영한다")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--report", type=Path, help="파일별 처리 결과를 JSON으로 저장한다")
    parser.add_argument("--activate", metavar="CODE")
    parser.add_argument("--deactivate", metavar="CODE")
    args = parser.parse_args(argv)

    if args.activate or args.deactivate:
        with SessionLocal() as db:
            try:
                course = service.set_active(db, args.activate or args.deactivate, bool(args.activate))
            except ValueError as error:
                print(error, file=sys.stderr)
                return 1
            print(f"{course.code} ({course.name}): {'추천 후보에 넣었어요' if course.is_active else '추천 후보에서 뺐어요'}")
        return 0
    if args.folder is None or not args.folder.is_dir():
        parser.error("GPX 폴더를 지정해 주세요.")

    # 서버 시작과 같은 경로로 스키마를 맞춘다. 고칠 것이 있으면 먼저 백업한다.
    backup_service.migrate(engine, get_settings())
    previous = {row["code"]: row for row in json.loads(args.output.read_text(encoding="utf-8"))} if args.output.exists() else {}
    if args.measure:
        # 앱 요청 중에는 오래 기다리지 않지만, 데이터 구축 때는 서버가 붐벼도 응답을 받도록 더 기다린다.
        environment_service.OVERPASS_TIMEOUT_SECONDS = 45.0
    started = time.perf_counter()
    results, rows = process(args.folder, args.measure, previous)
    elapsed = time.perf_counter() - started

    by_code = {row["code"]: row for row in rows}
    # 이번 폴더에 없는 이전 코스도 남긴다. 지우면 그 코스를 가리키는 산책 기록의 코스 정보가 서버 재시작 뒤에 갱신되지 않는다.
    merged = {**previous, **by_code}
    args.output.write_text(json.dumps(list(merged.values()), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    counts = {status: sum(1 for r in results if r.status == status) for status in ("ok", "duplicate", "error")}
    print(f"GPX {len(results)}개 처리 ({elapsed:.2f}초): 성공 {counts['ok']}, 중복 {counts['duplicate']}, 오류 {counts['error']}")
    for result in results:
        print(summary_line(result, by_code.get(result.code)))
        for warning in result.warnings:
            print(f"      - {warning}")
    print(f"저장: {args.output}")

    if args.apply and rows:
        with SessionLocal() as db:
            created, updated = service.upsert(db, rows)
        print(f"DB 반영: 새로 넣음 {created}, 갱신 {updated}")

    if args.report:
        report = [
            {
                "source_file": r.source_file,
                "status": r.status,
                "error": r.error,
                "code": r.code if r.status == "ok" else None,
                "duplicate_of": r.duplicate_of,
                "warnings": r.warnings,
                "sha256": r.sha256,
                **({k: by_code[r.code][k] for k in ("name", "area", "distance_km", "duration_min")} if r.code in by_code and r.status == "ok" else {}),
                "gpx": by_code[r.code]["data_sources"]["gpx"] if r.code in by_code and r.status == "ok" else None,
            }
            for r in results
        ]
        args.report.write_text(json.dumps({"elapsed_seconds": round(elapsed, 3), "counts": counts, "files": report}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if counts["error"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
