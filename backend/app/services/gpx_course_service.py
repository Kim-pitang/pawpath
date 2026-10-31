"""외부 GPX 파일을 추천 후보 코스로 바꾼다.

내 산책길(saved_walks)과 달리 주인이 없는 공용 코스이고, 시드 코스와 같은 `walking_courses` 행이 된다.
점수는 기존 엔진이 그대로 계산하므로, 여기서는 경로를 정제하고 측정값과 추정값, 확인 불가 항목을 나눠 적는 데 집중한다.

- 거리는 정제한 좌표의 Haversine 합이다(측정값).
- 시드 코스는 모두 출발점으로 돌아오는 길이라, 편도 GPX는 같은 길을 되돌아오는 왕복 코스로 만들어 같은 기준으로 비교한다.
  편도 길이와 원래 도착점은 `data_sources.gpx`에 남긴다.
- 고도가 없으면 상승, 하강, 경사를 비워 두고 난이도를 '확인 불가'로 둔다.
- 반려견 동반 허용, 혼잡도는 GPX로 알 수 없어 '확인 불가'로 둔다.
"""
import hashlib
import math
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import SERVICE_AREAS
from app.models import WalkingCourse
from app.recommender.diversity import DUPLICATE_OVERLAP, route_overlap
from app.services import environment_service
from app.services.gpx_service import GpxError, parse_gpx
from app.services.places_service import load_places
from app.services.saved_walk_service import haversine_m
from app.services.user_course_service import AREA_RADIUS_M, MAX_COURSE_KM, WALK_KMH, course_attributes, nearby_facilities

SOURCE_TYPE = "gpx_import"
CODE_PREFIX = "gpx-"
# 한국 밖이거나 (0, 0)처럼 기기가 위치를 못 잡았을 때 찍히는 좌표를 거른다.
KOREA_LAT = (33.0, 39.0)
KOREA_LNG = (124.0, 132.0)
# 이보다 가까운 연속 지점은 같은 지점으로 본다.
SAME_POINT_M = 0.5
# 앞뒤 지점은 가까운데 혼자 멀리 튄 지점(GPS 튐)을 뺀다.
SPIKE_OUT_M = 300.0
SPIKE_BACK_M = 50.0
# 길찾기 결과는 직선 구간의 중간 지점을 생략해 수백 m씩 떨어지기도 한다. 그보다 훨씬 먼 간격은 끊긴 경로로 본다.
MAX_SEGMENT_M = 2000.0
MIN_ONE_WAY_KM = 0.1
# 끝점이 출발점에서 이 거리(또는 경로 길이의 5%) 안이면 순환형이다.
LOOP_GAP_M = 50.0
LOOP_GAP_SHARE = 0.05
# 이 비율 이상 겹치면 같은 코스로 보고 등록하지 않는다. 0.6 이상은 등록하되 비슷한 코스로 적는다(추천 단계에서 한 번만 나온다).
SAME_ROUTE_OVERLAP = 0.9
# 고도 잡음을 누적하지 않도록 이보다 작은 오르내림은 버린다.
ELEVATION_STEP_M = 1.0
MEASURE_FAILED = "OSM 응답 실패"
PET_RULE = "반려견 동반 허용 여부를 확인하지 않은 코스예요. 리드줄과 배변봉투를 챙기고 현장 안내를 따라 주세요."


@dataclass
class Cleaning:
    raw_points: int
    invalid_coordinates: int = 0
    outside_korea: int = 0
    duplicates: int = 0
    spikes: int = 0


@dataclass
class GpxCourse:
    """파일 하나의 처리 결과. status는 ok, duplicate, error 중 하나다."""

    source_file: str
    status: str = "ok"
    error: str | None = None
    name: str | None = None
    district: str | None = None
    sha256: str | None = None
    points: list[list[float]] = field(default_factory=list)
    altitudes: list[float | None] = field(default_factory=list)
    cleaning: Cleaning | None = None
    one_way_km: float = 0.0
    route_type: str | None = None
    end_gap_m: float = 0.0
    longest_segment_m: float = 0.0
    elevation: dict | None = None
    has_time: bool = False
    warnings: list[str] = field(default_factory=list)
    similar: list[dict] = field(default_factory=list)
    duplicate_of: str | None = None
    values: dict | None = None

    @property
    def code(self) -> str:
        return course_code(self.source_file)


def normalize_name(name: str) -> str:
    """macOS는 한글 파일 이름을 자모로 풀어(NFD) 돌려준다. 운영체제와 관계없이 같은 코드가 나오도록 NFC로 맞춘다."""
    return unicodedata.normalize("NFC", name)


def course_code(source_file: str) -> str:
    """파일 이름에서 코스 코드를 만든다. 같은 파일을 다시 넣으면 같은 행을 갱신한다."""
    stem = Path(normalize_name(source_file)).stem
    code = f"{CODE_PREFIX}{stem}"
    if len(code) <= 50:
        return code
    return f"{CODE_PREFIX}{stem[:36]}-{hashlib.sha1(stem.encode()).hexdigest()[:8]}"


def clean_points(raw: list[tuple[float, float, float | None]]) -> tuple[list[list[float]], list[float | None], Cleaning]:
    """순서를 유지한 채 잘못된 좌표, 연속 중복, 튄 지점을 뺀다."""
    report = Cleaning(raw_points=len(raw))
    kept: list[tuple[float, float, float | None]] = []
    for lat, lng, ele in raw:
        if not (math.isfinite(lat) and math.isfinite(lng)) or (lat == 0 and lng == 0):
            report.invalid_coordinates += 1
            continue
        if not (KOREA_LAT[0] <= lat <= KOREA_LAT[1] and KOREA_LNG[0] <= lng <= KOREA_LNG[1]):
            report.outside_korea += 1
            continue
        if kept and haversine_m(kept[-1][0], kept[-1][1], lat, lng) < SAME_POINT_M:
            report.duplicates += 1
            continue
        kept.append((lat, lng, ele))

    index = 1
    while index < len(kept) - 1:
        before, here, after = kept[index - 1], kept[index], kept[index + 1]
        out = haversine_m(before[0], before[1], here[0], here[1])
        back = haversine_m(here[0], here[1], after[0], after[1])
        if out > SPIKE_OUT_M and back > SPIKE_OUT_M and haversine_m(before[0], before[1], after[0], after[1]) < SPIKE_BACK_M:
            del kept[index]
            report.spikes += 1
        else:
            index += 1
    return [[lat, lng] for lat, lng, _ in kept], [ele for _, _, ele in kept], report


def elevation_summary(altitudes: list[float | None], one_way_km: float) -> dict | None:
    """고도 기록이 있는 지점끼리 상승과 하강을 더한다. 기록이 없으면 None이다."""
    values = [value for value in altitudes if value is not None]
    if len(values) < 2:
        return None
    gain = loss = 0.0
    anchor = values[0]
    for value in values[1:]:
        if value - anchor >= ELEVATION_STEP_M:
            gain += value - anchor
            anchor = value
        elif anchor - value >= ELEVATION_STEP_M:
            loss += anchor - value
            anchor = value
    return {
        "gain_m": round(gain, 1),
        "loss_m": round(loss, 1),
        "min_m": round(min(values), 1),
        "max_m": round(max(values), 1),
        "gain_per_km": round(gain / one_way_km, 1) if one_way_km else None,
        "coverage": round(len(values) / len(altitudes), 3),
    }


def difficulty_of(elevation: dict | None) -> str | None:
    """1km당 상승 고도로 난이도를 정한다. 고도가 없으면 None(확인 불가)이다."""
    if not elevation or elevation.get("gain_per_km") is None or elevation["coverage"] < 0.8:
        return None
    per_km = elevation["gain_per_km"]
    return "hard" if per_km >= 40 else "moderate" if per_km >= 15 else "easy"


def district_of(source_file: str, name: str | None) -> str | None:
    """'강남구_양재천.gpx'처럼 자치구로 시작하는 파일 이름에서 구를 읽는다."""
    for text in (Path(source_file).stem.replace("_", " "), name or ""):
        first = text.split(" ", 1)[0]
        if first.endswith(("구", "군", "시")) and len(first) >= 2:
            return first
    return None


def area_of(start: list[float], district: str | None) -> tuple[str, bool]:
    """출발점이 서비스 지역 반경 안이면 그 지역, 아니면 자치구 단위 지역 이름. 두 번째 값은 서비스 지역 안인지다."""
    distances = {area.label: haversine_m(start[0], start[1], area.latitude, area.longitude) for area in SERVICE_AREAS.values()}
    label, distance = min(distances.items(), key=lambda item: item[1])
    if distance <= AREA_RADIUS_M:
        return label, True
    return (f"서울 {district} 일대" if district else "서비스 지역 밖"), False


def analyze(source_file: str, data: bytes) -> GpxCourse:
    """GPX 바이트 하나를 읽고 정제해 측정값을 채운다. DB는 보지 않는다."""
    source_file = normalize_name(source_file)
    result = GpxCourse(source_file=source_file, sha256=hashlib.sha256(data).hexdigest())
    try:
        parsed = parse_gpx(data)
    except GpxError as error:
        result.status, result.error = "error", str(error)
        return result

    result.name = (parsed.name or Path(source_file).stem).replace("_", " ")[:80]
    result.district = district_of(source_file, parsed.name)
    result.has_time = any(point.recorded_at for point in parsed.points)
    if parsed.track_count > 1 or len({point.segment for point in parsed.points}) > 1:
        result.warnings.append("트랙이나 구간이 여러 개라 순서대로 이어 붙였어요.")
    raw = [(point.latitude, point.longitude, point.altitude) for point in parsed.points]
    points, altitudes, cleaning = clean_points(raw)
    cleaning.invalid_coordinates += parsed.invalid_point_count
    cleaning.raw_points += parsed.invalid_point_count
    result.points, result.altitudes, result.cleaning = points, altitudes, cleaning

    if len(points) < 2:
        result.status, result.error = "error", "정제 후 남은 좌표가 2개보다 적어요."
        return result
    segments = [haversine_m(*a, *b) for a, b in zip(points, points[1:])]
    result.longest_segment_m = round(max(segments), 1)
    if result.longest_segment_m > MAX_SEGMENT_M:
        result.status, result.error = "error", f"이웃한 두 지점이 {result.longest_segment_m / 1000:.1f}km 떨어져 있어 끊긴 경로로 보여요."
        return result
    result.one_way_km = round(sum(segments) / 1000, 3)
    if result.one_way_km < MIN_ONE_WAY_KM:
        result.status, result.error = "error", "경로가 100m보다 짧아요."
        return result

    result.end_gap_m = round(haversine_m(*points[0], *points[-1]), 1)
    loop_limit = max(LOOP_GAP_M, result.one_way_km * 1000 * LOOP_GAP_SHARE)
    result.route_type = "circular" if result.end_gap_m <= loop_limit else "one_way"
    walk_km = result.one_way_km * (1 if result.route_type == "circular" else 2)
    if walk_km > MAX_COURSE_KM:
        result.status, result.error = "error", f"걷는 거리가 {walk_km:.1f}km라 추천 코스 상한 {MAX_COURSE_KM:.0f}km를 넘어요."
        return result

    result.elevation = elevation_summary(altitudes, result.one_way_km)
    if result.elevation is None:
        result.warnings.append("고도 기록이 없어 상승, 하강, 경사를 비워 두고 난이도를 확인 불가로 둬요.")
    if cleaning.invalid_coordinates or cleaning.outside_korea or cleaning.spikes:
        result.warnings.append(
            f"잘못된 좌표 {cleaning.invalid_coordinates}개, 국내 범위 밖 {cleaning.outside_korea}개, 튄 지점 {cleaning.spikes}개를 뺐어요."
        )
    return result


def course_route(result: GpxCourse) -> list[list[float]]:
    """추천과 길 안내에 쓰는 경로. 편도는 같은 길로 되돌아와 출발점에서 끝난다."""
    if result.route_type == "circular":
        return [list(point) for point in result.points]
    return [list(point) for point in result.points] + [list(point) for point in reversed(result.points[:-1])]


def build_values(result: GpxCourse, manifest: dict | None = None, environment: dict | None = None, environment_note: str | None = None) -> dict:
    """WalkingCourse 열 값. is_active는 넣지 않는다. 관리자가 끈 코스를 다시 적재할 때 켜지 않게 하기 위해서다."""
    manifest = manifest or {}
    route = course_route(result)
    walk_km = result.one_way_km * (1 if result.route_type == "circular" else 2)
    area, in_area = area_of(route[0], result.district)
    attributes, unknown = course_attributes(environment, recorded=False)
    difficulty = difficulty_of(result.elevation)
    if difficulty is not None:
        attributes["difficulty"] = difficulty
        unknown = [item for item in unknown if item != "difficulty"]

    places = load_places()
    facilities = nearby_facilities(route) if in_area else []
    shape = "순환" if result.route_type == "circular" else f"편도 {result.one_way_km:.2f}km를 되돌아오는 왕복"
    description = f"공개 GPX 경로로 만든 {shape} 코스예요. 실측 기록이 아니라 도보 길찾기로 계산한 길이라 현장 확인이 필요해요."
    if "우회" in manifest.get("검증상태", ""):
        description += " 길찾기가 돌아가는 구간이 있어 지도로 확인해 주세요."
    data_sources = {
        "source_type": SOURCE_TYPE,
        "source_file": result.source_file,
        "source_sha256": result.sha256,
        "route": manifest.get("경로출처") or "공개 GPX 경로(OSM 보행망 기반 길찾기 결과)",
        "facilities": f"OpenStreetMap ({places.get('collected_on')})" if in_area else None,
        "facilities_unavailable": None if in_area else "서비스 지역 밖이라 시설 자료를 수집하지 않았어요.",
        "environment": environment_note if environment else None,
        "environment_status": "done" if environment else ("failed" if (environment_note or "").startswith(MEASURE_FAILED) else "off"),
        "environment_unavailable": None if environment else (environment_note or "주변 환경을 측정하지 않았어요."),
        "team_estimates": [],
        "unknown": sorted({*unknown, "pet_allowed"}),
        "gpx": {
            "route_type": result.route_type,
            "one_way_km": round(result.one_way_km, 2),
            "start": result.points[0],
            "end": result.points[-1],
            "end_gap_m": result.end_gap_m,
            "point_count": len(result.points),
            "raw_point_count": result.cleaning.raw_points if result.cleaning else None,
            "cleaning": vars(result.cleaning) if result.cleaning else None,
            "longest_segment_m": result.longest_segment_m,
            "elevation": result.elevation,
            "has_time": result.has_time,
            "district": result.district,
            "in_service_area": in_area,
            "verification": manifest.get("검증상태") or None,
            "similar_courses": result.similar,
            # 측정값: 좌표, 거리, 고도. 추정값: 걷는 시간(시속 3.6km 가정). 왕복 거리는 편도 측정값의 두 배다.
            "measured": ["route", "one_way_km"] + (["elevation"] if result.elevation else []),
            "estimated": ["duration_min"] + ([] if result.route_type == "circular" else ["distance_km(왕복=편도×2)"]),
        },
    }
    return {
        "name": result.name,
        "description": description,
        "area": area,
        "start_lat": route[0][0],
        "start_lng": route[0][1],
        "distance_km": round(walk_km, 2),
        "duration_min": max(10, round(walk_km / WALK_KMH * 60 / 5) * 5),
        "route": route,
        "park_names": sorted({f["name"] for f in facilities if f["type"] == "park" and f["name"]}),
        "pet_allowed": True,
        "pet_rule_note": PET_RULE,
        "facilities": facilities,
        "environment": environment,
        "data_sources": data_sources,
        **attributes,
    }


def find_overlaps(results: list[GpxCourse], existing: list[WalkingCourse]) -> None:
    """같은 파일, 같은 경로를 중복으로 표시하고 비슷한 코스를 적는다. 순서대로 앞의 것을 남긴다."""
    seen_hashes: dict[str, str] = {}
    accepted: list[tuple[str, str, tuple]] = []
    others = [
        (course.code, course.name, tuple((p[0], p[1]) for p in course.route))
        for course in existing
        if not course.code.startswith(CODE_PREFIX) and course.is_active is not False and course.owner_user_id is None
    ]
    for result in results:
        if result.status != "ok":
            continue
        if result.sha256 in seen_hashes:
            result.status, result.duplicate_of = "duplicate", seen_hashes[result.sha256]
            result.error = f"{seen_hashes[result.sha256]}와 내용이 같은 파일이에요."
            continue
        route = tuple((p[0], p[1]) for p in course_route(result))
        for code, name, other in [*others, *accepted]:
            if code == result.code:
                continue
            overlap = route_overlap(route, other)
            if overlap >= SAME_ROUTE_OVERLAP:
                result.status, result.duplicate_of = "duplicate", code
                result.error = f"'{name}'와 경로가 {overlap:.0%} 겹쳐 같은 코스로 봐요."
                break
            if overlap >= DUPLICATE_OVERLAP:
                result.similar.append({"code": code, "name": name, "overlap": overlap})
        if result.status == "ok":
            seen_hashes[result.sha256] = result.source_file
            accepted.append((result.code, result.name, route))


def read_manifest(folder: Path) -> dict[str, dict]:
    """폴더에 '파일' 열이 있는 CSV가 있으면 파일 이름별 부가 정보를 읽는다. 없어도 된다."""
    import csv

    rows: dict[str, dict] = {}
    for path in sorted(folder.glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("파일"):
                    rows[normalize_name(row["파일"])] = row
    return rows


def measure(route: list[list[float]], collected_on: str) -> tuple[dict | None, str]:
    """Overpass로 주변 도로, 조명, 노면, 나무, 공원을 잰다. 실패하면 None과 이유를 돌려준다."""
    try:
        ways, trees, parks = environment_service.fetch_osm(route)
    except environment_service.EnvironmentUnavailable as error:
        return None, f"{MEASURE_FAILED}({error})"
    environment = environment_service.measure_environment(route, ways, trees, parks, collected_on)
    return environment, f"OpenStreetMap Overpass ({collected_on}), 경로 10m 간격 측정"


def upsert(db: Session, rows: list[dict]) -> tuple[int, int]:
    """코드 기준으로 넣거나 갱신한다. 새로 넣은 수와 갱신한 수를 돌려준다."""
    existing = {course.code: course for course in db.scalars(select(WalkingCourse).where(WalkingCourse.code.in_([row["code"] for row in rows])))}
    created = updated = 0
    for row in rows:
        course = existing.get(row["code"])
        if course is None:
            db.add(WalkingCourse(**row, is_active=True))
            created += 1
        else:
            for key, value in row.items():
                setattr(course, key, value)
            updated += 1
    db.commit()
    return created, updated


def set_active(db: Session, code: str, active: bool) -> WalkingCourse:
    course = db.scalar(select(WalkingCourse).where(WalkingCourse.code == code))
    if course is None or not code.startswith(CODE_PREFIX):
        raise ValueError(f"GPX로 등록한 코스가 아니에요: {code}")
    course.is_active = active
    db.commit()
    return course
