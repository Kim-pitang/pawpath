"""나만의 산책길: 저장, 조회, 공유. API와 DB 사이의 데이터 접근 계층이다."""
import hashlib
import math
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas
from app.clock import now_local
from app.models import Profile, SavedWalk, SavedWalkPoint, User
from app.services.gpx_service import GpxPoint, ParsedGpx

EARTH_RADIUS_M = 6371000.0
# 시각이 있으면 이 속도, 없으면 이 간격을 넘는 이동은 같은 길로 이어 그리지 않는다. 지점은 지우지 않는다.
MAX_PLAUSIBLE_SPEED_MPS = 70.0
MAX_UNTIMED_GAP_M = 5000.0
# 시각 차이가 아주 작으면 몇 미터만 움직여도 속도가 커 보인다. 이보다 짧은 이동은 순간 이동으로 보지 않는다.
MIN_JUMP_M = 100.0
PREVIEW_MAX_POINTS = 80
TOKEN_BYTES = 24


@dataclass
class TrackMetrics:
    distance_m: float
    duration_sec: int | None
    started_at: datetime | None
    ended_at: datetime | None
    average_speed_mps: float | None


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def split_impossible_jumps(points: list[GpxPoint]) -> tuple[list[GpxPoint], int]:
    """불가능한 순간 이동이 있으면 그곳에서 구간을 나눈다. 순서와 지점은 그대로 둔다."""
    result: list[GpxPoint] = []
    shift = 0
    jumps = 0
    for point in points:
        moved = GpxPoint(point.segment + shift, point.latitude, point.longitude, point.altitude, point.recorded_at)
        if result and result[-1].segment == moved.segment:
            last = result[-1]
            distance = haversine_m(last.latitude, last.longitude, moved.latitude, moved.longitude)
            seconds = (moved.recorded_at - last.recorded_at).total_seconds() if last.recorded_at and moved.recorded_at else None
            if seconds is not None and seconds > 0:
                impossible = distance > MIN_JUMP_M and distance / seconds > MAX_PLAUSIBLE_SPEED_MPS
            else:
                # 시각이 없거나, 같거나(모든 지점에 같은 시각을 찍는 파일이 있다), 거꾸로 가면 속도를 알 수 없다.
                # 이때는 아주 먼 간격만 나눈다.
                impossible = distance > MAX_UNTIMED_GAP_M
            if impossible:
                shift += 1
                jumps += 1
                moved.segment += 1
        result.append(moved)
    return result, jumps


def remove_consecutive_duplicates(points: list[GpxPoint]) -> list[GpxPoint]:
    """같은 구간에서 좌표가 그대로인 지점을 뺀다. 기록한 산책에만 쓴다."""
    kept: list[GpxPoint] = []
    for point in points:
        last = kept[-1] if kept else None
        if last and last.segment == point.segment and (last.latitude, last.longitude) == (point.latitude, point.longitude):
            continue
        kept.append(point)
    return kept


def measure_track(points: list[GpxPoint], duration_sec: int | None = None) -> TrackMetrics:
    """구간 안에서만 거리와 시간을 더한다. 일시정지나 끊긴 구간 사이는 세지 않는다."""
    distance = 0.0
    seconds = 0.0
    timed = False
    for previous, point in zip(points, points[1:]):
        if previous.segment != point.segment:
            continue
        distance += haversine_m(previous.latitude, previous.longitude, point.latitude, point.longitude)
        if previous.recorded_at and point.recorded_at:
            timed = True
            seconds += max(0.0, (point.recorded_at - previous.recorded_at).total_seconds())
    times = [point.recorded_at for point in points if point.recorded_at]
    duration = duration_sec if duration_sec is not None else (round(seconds) if timed else None)
    return TrackMetrics(
        distance_m=round(distance, 1),
        duration_sec=duration,
        started_at=min(times) if times else None,
        ended_at=max(times) if times else None,
        average_speed_mps=round(distance / duration, 3) if duration else None,
    )


def route_hash(points: list[GpxPoint]) -> str:
    """같은 경로인지 비교하는 값. 소수 다섯째 자리(약 1m)까지만 본다."""
    text = ";".join(f"{point.latitude:.5f},{point.longitude:.5f}" for point in points)
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def route_segments(points: list[GpxPoint | SavedWalkPoint]) -> list[list[list[float]]]:
    segments: dict[int, list[list[float]]] = {}
    for point in points:
        segments.setdefault(point.segment, []).append([point.latitude, point.longitude])
    return list(segments.values())


def thumbnail_route(points: list[GpxPoint]) -> list[list[list[float]]]:
    """목록 썸네일용으로 줄인 경로. 구간과 양 끝은 유지한다."""
    step = max(1, math.ceil(len(points) / PREVIEW_MAX_POINTS))
    picked = [point for index, point in enumerate(points) if index % step == 0 or index == len(points) - 1]
    return route_segments(picked)


def find_duplicate(db: Session, user: User, hash_value: str) -> SavedWalk | None:
    return db.scalar(
        select(SavedWalk).where(SavedWalk.user_id == user.id, SavedWalk.route_hash == hash_value).order_by(SavedWalk.id).limit(1)
    )


def preview_gpx(db: Session, user: User, parsed: ParsedGpx) -> dict:
    points, jumps = split_impossible_jumps(parsed.points)
    metrics = measure_track(points)
    warnings = list(parsed.warnings)
    if jumps:
        warnings.append(f"순간 이동으로 보이는 곳 {jumps}군데는 선을 잇지 않고 거리에서도 뺐어요.")
    has_time = any(point.recorded_at for point in points)
    if not has_time:
        warnings.append("시각 정보가 없어 소요 시간과 평균 속도를 계산할 수 없어요. 날짜는 가져온 날로 저장돼요.")
    elif not all(point.recorded_at for point in points):
        warnings.append("일부 지점에만 시각이 있어요. 시간은 시각이 있는 구간으로만 계산했어요.")
    times = [point.recorded_at for point in points if point.recorded_at]
    if any(later < earlier for earlier, later in zip(times, times[1:])):
        warnings.append("시각 순서가 뒤바뀐 지점이 있어요. 파일의 순서를 그대로 유지했어요.")
    duplicate = find_duplicate(db, user, route_hash(points))
    return {
        "name": parsed.name,
        "version": parsed.version,
        "track_count": parsed.track_count,
        "segment_count": len({point.segment for point in points}),
        "point_count": len(points),
        "invalid_point_count": parsed.invalid_point_count,
        "has_timestamps": has_time,
        "distance_m": metrics.distance_m,
        "duration_sec": metrics.duration_sec,
        "started_at": metrics.started_at,
        "ended_at": metrics.ended_at,
        "average_speed_mps": metrics.average_speed_mps,
        "warnings": warnings,
        "duplicate_of": {"id": duplicate.id, "title": duplicate.title} if duplicate else None,
        "points": points,
    }


def _new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def _apply_visibility(walk: SavedWalk, visibility: str) -> None:
    """비공개로 돌리면 토큰을 없애 예전 링크가 다시 살아나지 않게 한다."""
    walk.visibility = visibility
    if visibility == "private":
        walk.share_token = None
        walk.share_expires_at = None
        return
    if walk.share_token is None:
        walk.share_token = _new_token()
    if visibility == "public":
        walk.share_expires_at = None


def create_saved_walk(db: Session, user: User, body: schemas.SavedWalkCreate, profile: Profile) -> tuple[SavedWalk, bool]:
    """산책길을 저장한다. 같은 client_id로 다시 보내면 새로 만들지 않고 저장된 것을 돌려준다."""
    if body.client_id:
        existing = db.scalar(select(SavedWalk).where(SavedWalk.client_id == body.client_id, SavedWalk.user_id == user.id))
        if existing:
            return existing, False

    points = [GpxPoint(p.segment, p.latitude, p.longitude, p.altitude, p.recorded_at) for p in body.points]
    accuracies = [p.accuracy for p in body.points]
    if body.source_type == "recorded":
        kept = remove_consecutive_duplicates(points)
        kept_ids = {id(point) for point in kept}
        accuracies = [accuracy for point, accuracy in zip(points, accuracies) if id(point) in kept_ids]
        points = kept
    points, _ = split_impossible_jumps(points)
    metrics = measure_track(points, body.duration_sec if body.source_type == "recorded" else None)

    walk = SavedWalk(
        user_id=user.id,
        profile_id=profile.id,
        pet_id=body.pet_id,
        title=body.title,
        memo=body.memo,
        source_type=body.source_type,
        started_at=metrics.started_at or now_local(),
        ended_at=metrics.ended_at,
        distance_m=metrics.distance_m,
        duration_sec=metrics.duration_sec,
        average_speed_mps=metrics.average_speed_mps,
        has_timestamps=metrics.started_at is not None,
        point_count=len(points),
        route_hash=route_hash(points),
        preview=thumbnail_route(points),
        share_memo=body.share_memo,
        client_id=body.client_id,
    )
    _apply_visibility(walk, body.visibility)
    walk.points = [
        SavedWalkPoint(
            sequence=index,
            segment=point.segment,
            latitude=point.latitude,
            longitude=point.longitude,
            altitude=point.altitude,
            recorded_at=point.recorded_at,
            accuracy=accuracy,
        )
        for index, (point, accuracy) in enumerate(zip(points, accuracies))
    ]
    db.add(walk)
    try:
        db.commit()
    except IntegrityError:
        # 같은 요청이 동시에 들어와 먼저 저장된 경우다.
        db.rollback()
        existing = db.scalar(select(SavedWalk).where(SavedWalk.client_id == body.client_id, SavedWalk.user_id == user.id))
        if existing is None:
            raise
        return existing, False
    return walk, True


def list_saved_walks(db: Session, user: User, sort: str, pet_id: int | None, visibility: str | None, profile_id: int | None = None) -> list[SavedWalk]:
    """대표 계정의 산책길 목록. profile_id를 주면 그 프로필이 만든 것만 돌려준다."""
    query = select(SavedWalk).where(SavedWalk.user_id == user.id)
    if profile_id is not None:
        query = query.where(SavedWalk.profile_id == profile_id)
    if pet_id is not None:
        query = query.where(SavedWalk.pet_id == pet_id)
    if visibility is not None:
        query = query.where(SavedWalk.visibility == visibility)
    order = SavedWalk.distance_m.desc() if sort == "distance" else SavedWalk.started_at.desc()
    return list(db.scalars(query.order_by(order, SavedWalk.id.desc())))


def update_saved_walk(db: Session, walk: SavedWalk, changes: dict) -> SavedWalk:
    visibility = changes.pop("visibility", None)
    for key, value in changes.items():
        setattr(walk, key, value)
    if visibility is not None:
        _apply_visibility(walk, visibility)
    db.commit()
    return walk


def enable_share(db: Session, walk: SavedWalk, body: schemas.ShareRequest, now: datetime) -> SavedWalk:
    """공유 링크를 만든다. 비공개면 링크 공유로 바꾸고, 만료된 링크는 새 토큰으로 교체한다."""
    expired = walk.share_expires_at is not None and walk.share_expires_at <= now
    if expired:
        walk.share_token = None
    _apply_visibility(walk, "link" if walk.visibility == "private" else walk.visibility)
    if walk.visibility == "link":
        walk.share_expires_at = now + timedelta(days=body.expires_in_days) if body.expires_in_days else None
    walk.share_memo = body.share_memo
    db.commit()
    return walk


def disable_share(db: Session, walk: SavedWalk) -> SavedWalk:
    _apply_visibility(walk, "private")
    db.commit()
    return walk


def find_shared(db: Session, token: str) -> SavedWalk | None:
    return db.scalar(select(SavedWalk).where(SavedWalk.share_token == token, SavedWalk.visibility != "private"))


def is_expired(walk: SavedWalk, now: datetime) -> bool:
    return walk.share_expires_at is not None and walk.share_expires_at <= now


def shared_payload(walk: SavedWalk) -> dict:
    """다른 사람에게 보여 줄 값만 담는다. 시각, 정확도, 반려동물, 보호자 정보는 넣지 않는다."""
    segments = route_segments(walk.points)
    return {
        "title": walk.title,
        "distance_m": walk.distance_m,
        "duration_sec": walk.duration_sec,
        "memo": walk.memo if walk.share_memo else None,
        "start": segments[0][0],
        "end": segments[-1][-1],
        "route": segments,
    }


def list_public_walks(db: Session) -> list[SavedWalk]:
    return list(db.scalars(select(SavedWalk).where(SavedWalk.visibility == "public").order_by(SavedWalk.started_at.desc(), SavedWalk.id.desc())))


def public_summary(walk: SavedWalk) -> dict:
    return {
        "token": walk.share_token,
        "title": walk.title,
        "distance_m": walk.distance_m,
        "duration_sec": walk.duration_sec,
        "preview": walk.preview,
    }


def to_gpx_points(walk: SavedWalk) -> list[GpxPoint]:
    return [GpxPoint(p.segment, p.latitude, p.longitude, p.altitude, p.recorded_at) for p in walk.points]
