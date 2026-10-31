"""GPX 파일 읽기와 쓰기. DB를 모르는 순수 모듈이다.

expat을 직접 써서 DOCTYPE과 엔티티 선언을 만나면 바로 거부한다. 외부 엔티티(XXE)와
엔티티 폭탄이 들어올 길을 막기 위해서다. GPX 표준에는 DOCTYPE이 필요 없다.
"""
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import quote
from xml.parsers import expat
from xml.sax.saxutils import escape, quoteattr
from zoneinfo import ZoneInfo

from app.config import get_settings

MAX_GPX_BYTES = 10 * 1024 * 1024
MAX_POINTS = 100_000
GPX_VERSIONS = ("1.0", "1.1")
# 버전 표기를 빠뜨린 실제 기기 파일이 있어 거부하지 않고 경고만 한다.
VERSION_MISSING = "표기 없음"
GPX_NAMESPACE = "http://www.topografix.com/GPX/1/1"
TRACK_POINT_PARENTS = {"trkpt": "trkseg", "rtept": "rte"}


class GpxError(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 GPX 오류."""


@dataclass
class GpxPoint:
    segment: int
    latitude: float
    longitude: float
    altitude: float | None = None
    recorded_at: datetime | None = None


@dataclass
class ParsedGpx:
    version: str
    name: str | None
    track_count: int
    points: list[GpxPoint]
    invalid_point_count: int = 0
    invalid_time_count: int = 0
    used_routes: bool = False
    warnings: list[str] = field(default_factory=list)


def _service_timezone() -> ZoneInfo:
    return ZoneInfo(get_settings().service_timezone)


def _parse_time(text: str) -> datetime | None:
    """GPX 시각을 서비스 현지 시각으로 바꾼다. 시간대 표기가 없으면 표준대로 UTC로 본다."""
    try:
        value = datetime.fromisoformat(text.strip())
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    try:
        return value.astimezone(_service_timezone()).replace(tzinfo=None)
    except (OverflowError, ValueError):
        return None


def _parse_coordinate(text: str | None, limit: float) -> float | None:
    if text is None:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) and abs(value) <= limit else None


class _GpxReader:
    def __init__(self) -> None:
        self.stack: list[str] = []
        self.root_seen = False
        self.version: str | None = None
        self.name: str | None = None
        self.waypoints = 0
        self.track_count = 0
        self.points: list[GpxPoint] = []
        self.invalid_points = 0
        self.invalid_times = 0
        self.used_routes = False
        self.segment = -1
        self.current: GpxPoint | None = None
        self.text: list[str] | None = None

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit(" ", 1)[-1]

    def start(self, tag: str, attributes: dict[str, str]) -> None:
        local = self._local_name(tag)
        parent = self.stack[-1] if self.stack else None
        if parent is None:
            if local != "gpx":
                raise GpxError("GPX 파일이 아니에요. 최상위 요소가 gpx가 아닙니다.")
            self.root_seen = True
            self.version = attributes.get("version", VERSION_MISSING)
            if self.version not in (*GPX_VERSIONS, VERSION_MISSING):
                raise GpxError(f"지원하지 않는 GPX 버전이에요. {' 또는 '.join(GPX_VERSIONS)}만 읽을 수 있어요.")
        elif local == "wpt" and parent == "gpx":
            self.waypoints += 1
        elif local == "trk" and parent == "gpx":
            self.track_count += 1
        elif local == "rte" and parent == "gpx":
            self.track_count += 1
            self.used_routes = True
            self.segment += 1
        elif local == "trkseg" and parent == "trk":
            self.segment += 1
        elif TRACK_POINT_PARENTS.get(local) == parent:
            self.current = self._start_point(attributes)
        elif local in ("ele", "time") and parent in TRACK_POINT_PARENTS:
            self.text = []
        elif local == "name" and parent in ("metadata", "trk", "rte", "gpx") and self.name is None:
            self.text = []
        self.stack.append(local)

    def _start_point(self, attributes: dict[str, str]) -> GpxPoint | None:
        latitude = _parse_coordinate(attributes.get("lat"), 90)
        longitude = _parse_coordinate(attributes.get("lon"), 180)
        if latitude is None or longitude is None:
            self.invalid_points += 1
            return None
        if len(self.points) >= MAX_POINTS:
            raise GpxError(f"트랙 포인트가 너무 많아요. {MAX_POINTS:,}개까지 가져올 수 있어요.")
        return GpxPoint(segment=self.segment, latitude=latitude, longitude=longitude)

    def characters(self, data: str) -> None:
        if self.text is not None:
            self.text.append(data)

    def end(self, tag: str) -> None:
        local = self._local_name(tag)
        self.stack.pop()
        parent = self.stack[-1] if self.stack else None
        if self.text is not None and local in ("ele", "time", "name"):
            self._finish_text(local, "".join(self.text))
            self.text = None
        elif TRACK_POINT_PARENTS.get(local) == parent and self.current is not None:
            self.points.append(self.current)
            self.current = None

    def _finish_text(self, local: str, text: str) -> None:
        if local == "name":
            self.name = text.strip() or None
        elif self.current is None:
            return
        elif local == "ele":
            self.current.altitude = _parse_coordinate(text, 20_000)
        else:
            self.current.recorded_at = _parse_time(text)
            if self.current.recorded_at is None:
                self.invalid_times += 1


def _reject_declaration(*_args) -> None:
    raise GpxError("보안을 위해 DOCTYPE이나 엔티티 선언이 있는 파일은 읽지 않아요.")


def parse_gpx(data: bytes) -> ParsedGpx:
    """GPX 바이트를 읽어 트랙 포인트를 원래 순서대로 돌려준다. 잘못된 파일은 GpxError를 낸다."""
    if not data.strip():
        raise GpxError("빈 파일이에요.")
    if len(data) > MAX_GPX_BYTES:
        raise GpxError(f"파일이 너무 커요. {MAX_GPX_BYTES // (1024 * 1024)}MB까지 가져올 수 있어요.")

    reader = _GpxReader()
    parser = expat.ParserCreate(namespace_separator=" ")
    parser.buffer_text = True
    parser.StartDoctypeDeclHandler = _reject_declaration
    parser.EntityDeclHandler = _reject_declaration
    parser.ExternalEntityRefHandler = _reject_declaration
    parser.StartElementHandler = reader.start
    parser.EndElementHandler = reader.end
    parser.CharacterDataHandler = reader.characters
    try:
        parser.Parse(data, True)
    except GpxError:
        raise
    except (expat.ExpatError, LookupError, ValueError) as error:
        raise GpxError("파일 형식이 올바르지 않아요. UTF-8로 저장된 GPX인지 확인해 주세요.") from error

    if not reader.root_seen:
        raise GpxError("GPX 파일이 아니에요.")
    if not reader.points and reader.invalid_points:
        raise GpxError(f"위도와 경도가 올바르지 않은 지점만 있어요({reader.invalid_points}개). 좌표가 숫자로 기록된 파일인지 확인해 주세요.")
    if not reader.points and reader.waypoints:
        raise GpxError(f"걸은 길(트랙) 없이 장소 표시(waypoint) {reader.waypoints}개만 있는 파일이에요. 트랙이 들어 있는 GPX를 골라 주세요.")
    if not reader.points:
        raise GpxError("파일에 쓸 수 있는 좌표가 없어요. 트랙이 들어 있는 GPX인지 확인해 주세요.")
    if len(reader.points) < 2:
        raise GpxError("경로를 만들려면 좌표가 2개 이상 필요해요.")

    warnings = []
    if reader.version == VERSION_MISSING:
        warnings.append("GPX 버전 표기가 없어 표준 형식으로 읽었어요.")
    if reader.invalid_points:
        warnings.append(f"좌표가 잘못된 지점 {reader.invalid_points}개를 뺐어요.")
    if reader.invalid_times:
        warnings.append(f"시각을 읽을 수 없는 지점이 {reader.invalid_times}개 있어요.")
    if reader.used_routes:
        warnings.append("트랙 대신 경로(rte)를 읽었어요. 시각 정보는 없을 수 있어요.")
    if reader.track_count > 1:
        warnings.append(f"트랙 {reader.track_count}개를 하나의 산책길로 합쳤어요.")
    return ParsedGpx(
        version=reader.version,
        name=reader.name,
        track_count=reader.track_count,
        points=reader.points,
        invalid_point_count=reader.invalid_points,
        invalid_time_count=reader.invalid_times,
        used_routes=reader.used_routes,
        warnings=warnings,
    )


def _utc_text(value: datetime) -> str:
    utc = value.replace(tzinfo=_service_timezone()).astimezone(timezone.utc)
    text = utc.strftime("%Y-%m-%dT%H:%M:%S")
    if utc.microsecond:
        text += f".{utc.microsecond:06d}".rstrip("0")
    return f"{text}Z"


def _number(value: float) -> str:
    """반올림하지 않고 원래 값을 그대로 쓴다. GPX는 지수 표기(1e-05)를 받지 않으므로 풀어 쓴다."""
    return format(Decimal(repr(value)), "f")


def _strip_xml_invalid(text: str) -> str:
    """XML 1.0에 넣을 수 없는 제어 문자를 지운다."""
    return re.sub(r"[^\t\n\r -퟿-�\U00010000-\U0010FFFF]", "", text)


def build_gpx(name: str, points: list[GpxPoint], include_details: bool = True) -> bytes:
    """GPX 1.1 파일을 만든다. include_details가 거짓이면 공유용으로 시각과 고도를 뺀다."""
    safe_name = escape(_strip_xml_invalid(name))
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<gpx version="1.1" creator="PawPath" xmlns="{GPX_NAMESPACE}" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        f'xsi:schemaLocation="{GPX_NAMESPACE} {GPX_NAMESPACE}/gpx.xsd">',
        f"  <metadata><name>{safe_name}</name></metadata>",
        f"  <trk><name>{safe_name}</name>",
    ]
    segment: int | None = None
    for point in points:
        if point.segment != segment:
            if segment is not None:
                lines.append("  </trkseg>")
            lines.append("  <trkseg>")
            segment = point.segment
        details = ""
        if include_details and point.altitude is not None:
            details += f"<ele>{_number(point.altitude)}</ele>"
        if include_details and point.recorded_at is not None:
            details += f"<time>{_utc_text(point.recorded_at)}</time>"
        attributes = f"lat={quoteattr(_number(point.latitude))} lon={quoteattr(_number(point.longitude))}"
        lines.append(f"    <trkpt {attributes}>{details}</trkpt>" if details else f"    <trkpt {attributes}/>")
    if segment is not None:
        lines.append("  </trkseg>")
    lines += ["  </trk>", "</gpx>", ""]
    return "\n".join(lines).encode("utf-8")


def _slug(title: str, ascii_only: bool = False) -> str:
    """파일 이름에 쓸 수 없는 문자를 하이픈으로 바꾼다. ascii_only가 아니면 한글은 남긴다."""
    pattern = r"[^a-z0-9]+" if ascii_only else r"[^\w]+"
    slug = re.sub(pattern, "-", title.strip().lower(), flags=re.UNICODE).strip("-_")
    return slug[:40].strip("-_") or "walk"


def gpx_filename(title: str, date: datetime | None, ascii_only: bool = False) -> str:
    stamp = f"_{date:%Y%m%d}" if date else ""
    return f"pawpath_{_slug(title, ascii_only)}{stamp}.gpx"


def content_disposition(title: str, date: datetime | None) -> str:
    """브라우저는 RFC 5987의 한글 이름을 쓰고, 한글을 모르는 프로그램은 영문 대체 이름을 쓴다."""
    return f"attachment; filename=\"{gpx_filename(title, date, ascii_only=True)}\"; filename*=UTF-8''{quote(gpx_filename(title, date))}"
