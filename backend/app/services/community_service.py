"""산책길 커뮤니티: 내 산책길을 공개하고, 둘러보고, 좋아요와 저장, 후기를 남긴다.

좌표는 saved_walk_points에 한 벌만 둔다. 공개할 때는 출발점과 도착점 반경 안의 지점을 서버에서 빼고,
지도, 썸네일, GPX, 길 안내가 모두 가린 경로만 쓴다. 집 위치가 드러나지 않게 하기 위해서다.
좋아요 수와 평점은 저장하지 않고 읽을 때 집계해 실제 행과 어긋나지 않게 한다.
"""
import math
import secrets
from datetime import datetime

from sqlalchemy import String, case, cast, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import schemas
from app.clock import now_local
from app.config import SERVICE_AREAS
from app.models import CommunityTrail, Pet, SavedWalk, SavedWalkPhoto, TrailBookmark, TrailLike, TrailReview, TrailReviewPhoto, User, WalkHistory, WalkingCourse
from app.recommender.features import build_features
from app.services import environment_service
from app.services.gpx_service import GpxPoint
from app.services.places_service import load_places
from app.services.recommendation_service import to_profile
from app.services.saved_walk_service import haversine_m, measure_track, route_segments, thumbnail_route, to_gpx_points
from app.services.user_course_service import AREA_RADIUS_M, PET_RULE, CourseError, course_attributes, join_points, nearby_facilities, route_km, simplify

# 커뮤니티는 실제로 걸은 길을 나누는 곳이다. 자동 생성 경로는 아직 아무도 걷지 않았다.
SHAREABLE_SOURCES = {"recorded", "imported"}
# 가린 뒤에 이보다 짧게 남으면 공개할 길이 없는 것으로 본다.
MIN_PUBLIC_M = 100.0
# 평균 속도를 믿을 수 없을 때 쓰는 걸음 속도(시속 3.6km). 내 산책길 코스의 예상 시간과 같은 값이다.
DEFAULT_SPEED_MPS = 1.0
PLAUSIBLE_SPEED_MPS = (0.3, 3.0)
# GPS 고도의 흔들림을 오르막으로 세지 않으려고, 이만큼 오른 뒤에만 더한다.
CLIMB_STEP_M = 5.0
LABEL_RADIUS_M = 300.0
LABEL_PLACE_TYPES = {"park", "dog_park"}
OTHER_REGION = "기타 지역"
# 공유를 거둔 코스. 다른 보호자의 산책 기록이 가리키므로 행은 남기되, 경로와 이름과 주인을 지워 다시 열리지 않게 한다.
RETIRED_COURSE = {
    "owner_user_id": None,
    "community_trail_id": None,
    "is_active": False,
    "name": "삭제된 커뮤니티 산책길",
    "description": "",
    "start_lat": 0.0,
    "start_lng": 0.0,
    "route": [],
    "facilities": [],
    "park_names": [],
    "data_sources": {},
}
# 후기 한두 개로 순위가 뒤집히지 않도록, 평점순은 후기 3개 분량의 평균값(3.5점)을 섞어 계산한다.
RATING_PRIOR = 3.5
RATING_PRIOR_COUNT = 3
POPULARITY_WEIGHTS = {"like": 3, "bookmark": 2, "review": 2, "view": 0.1}
# 이 코스를 실제 걸은 거리의 비율이 이보다 높고 GPS로 기록했으면 '산책 인증'으로 표시한다.
VERIFIED_SHARE = 0.5
MAX_REVIEW_PHOTOS = 3
RECOMMEND_CANDIDATES = 300
RECOMMEND_WEIGHTS = {"distance": 0.35, "suitable": 0.2, "quality": 0.2, "taste": 0.15, "terrain": 0.1}
FEATURE_TO_ATTRIBUTE = {"park": "park", "shade": "shade", "waterside": "river", "forest": "forest", "quiet": "quiet", "lit": "lit", "paved": "paved"}
HILL_BY_DIFFICULTY = {"easy": 0.0, "moderate": 0.6, "hard": 1.0}
SUITABLE_LABELS = {"small": "소형견", "medium": "중형견", "large": "대형견", "senior": "노령견", "puppy": "어린 강아지", "active": "활동량 많은 아이", "timid": "겁 많은 아이"}


class CommunityError(Exception):
    """화면에 그대로 보여 줄 수 있는 실패 이유."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# ---------- 공개 경로
def _passes_near(a: GpxPoint, a_gaps: tuple, b: GpxPoint, b_gaps: tuple, anchors: tuple, radius_m: float) -> bool:
    """지점이 드문 GPX는 두 지점이 모두 반경 밖이어도 그 사이 선이 반경 안을 지날 수 있다."""
    hop = haversine_m(a.latitude, a.longitude, b.latitude, b.longitude)
    for anchor, a_gap, b_gap in zip(anchors, a_gaps, b_gaps):
        # 삼각 부등식으로 닿을 수 없는 구간은 계산을 건너뛴다.
        if a_gap + b_gap < hop + 2 * radius_m:
            origin = anchor.latitude
            center = environment_service.to_xy(anchor.latitude, anchor.longitude, origin)
            if environment_service.point_segment_m(center, environment_service.to_xy(a.latitude, a.longitude, origin), environment_service.to_xy(b.latitude, b.longitude, origin)) < radius_m:
                return True
    return False


def public_points(points: list[GpxPoint], radius_m: float) -> list[GpxPoint]:
    """출발점과 도착점 반경 안의 지점을 뺀다. 길 중간에 다시 그 근처를 지나도 뺀다. 시각은 옮기지 않는다."""
    if not points:
        return []
    anchors = (points[0], points[-1])
    runs: list[list[GpxPoint]] = []
    previous, previous_gaps = None, ()
    for point in points:
        gaps = tuple(haversine_m(point.latitude, point.longitude, anchor.latitude, anchor.longitude) for anchor in anchors)
        if min(gaps) < radius_m:
            previous = None
            continue
        if previous is None or previous.segment != point.segment or _passes_near(previous, previous_gaps, point, gaps, anchors, radius_m):
            runs.append([])
        runs[-1].append(point)
        previous, previous_gaps = point, gaps
    kept = [run for run in runs if len(run) >= 2]
    return [GpxPoint(index, point.latitude, point.longitude, point.altitude) for index, run in enumerate(kept) for point in run]


def public_route(walk: SavedWalk, radius_m: int) -> list[GpxPoint]:
    return public_points(to_gpx_points(walk), radius_m)


def trail_points(trail: CommunityTrail) -> list[GpxPoint]:
    return public_route(trail.walk, trail.hide_radius_m)


def elevation_gain_m(points: list[GpxPoint]) -> float | None:
    """오르막 누적. 고도가 있는 지점이 절반이 안 되면 알 수 없는 것으로 둔다."""
    known = [point.altitude for point in points if point.altitude is not None]
    if len(known) < 2 or len(known) * 2 < len(points):
        return None
    gain = 0.0
    base = known[0]
    for altitude in known[1:]:
        if altitude - base >= CLIMB_STEP_M:
            gain += altitude - base
            base = altitude
        elif altitude < base:
            base = altitude
    return round(gain, 1)


def difficulty_of(distance_m: float, gain_m: float | None) -> str:
    """거리와 오르막으로 정하는 난이도. 고도가 없으면 거리로만 정한다."""
    km = distance_m / 1000
    climb = gain_m or 0.0
    if km >= 5 or climb >= 100:
        return "hard"
    if km >= 2 or climb >= 30:
        return "moderate"
    return "easy"


def _estimated_min(walk: SavedWalk, distance_m: float) -> int:
    speed = walk.average_speed_mps
    if speed is None or not PLAUSIBLE_SPEED_MPS[0] <= speed <= PLAUSIBLE_SPEED_MPS[1]:
        speed = DEFAULT_SPEED_MPS
    return max(1, round(distance_m / speed / 60))


def suggest_region(latitude: float, longitude: float) -> str:
    """서비스 지역 근처면 그 이름을 쓴다. 주소 검색은 외부에 위치를 보내게 되어 쓰지 않는다."""
    distances = {area.label: haversine_m(latitude, longitude, area.latitude, area.longitude) for area in SERVICE_AREAS.values()}
    label, distance = min(distances.items(), key=lambda item: item[1])
    return label if distance <= AREA_RADIUS_M else OTHER_REGION


def place_label(latitude: float, longitude: float) -> str | None:
    """미리 수집한 OSM 자료에서 가장 가까운 공원 이름. 없으면 비워 두고 지도로 안내한다."""
    best, best_distance = None, LABEL_RADIUS_M
    for place in load_places()["places"]:
        if place["type"] in LABEL_PLACE_TYPES and place.get("name"):
            distance = haversine_m(latitude, longitude, place["lat"], place["lng"])
            if distance <= best_distance:
                best, best_distance = place["name"], distance
    return f"{best} 근처" if best else None


def _public_values(walk: SavedWalk, points: list[GpxPoint], radius_m: int) -> dict:
    distance = measure_track(points).distance_m
    if len(points) < 2 or distance < MIN_PUBLIC_M:
        raise CommunityError(422, f"출발점과 도착점 주변 {radius_m}m를 가리면 남는 길이 너무 짧아요. 가리는 범위를 줄이거나 더 긴 산책길을 골라 주세요.")
    gain = elevation_gain_m(points)
    first, last = points[0], points[-1]
    return {
        "distance_m": distance,
        "estimated_min": _estimated_min(walk, distance),
        "elevation_gain_m": gain,
        "difficulty": difficulty_of(distance, gain),
        "start_lat": first.latitude,
        "start_lng": first.longitude,
        "end_lat": last.latitude,
        "end_lng": last.longitude,
        "start_label": place_label(first.latitude, first.longitude),
        "end_label": place_label(last.latitude, last.longitude),
        "preview": thumbnail_route(points),
    }


def can_navigate(points: list[GpxPoint]) -> bool:
    try:
        return len(join_points(points)) >= 2
    except CourseError:
        return False


def _check_shareable(walk: SavedWalk) -> None:
    if walk.source_type not in SHAREABLE_SOURCES:
        raise CommunityError(422, "직접 걸은 길만 공유할 수 있어요. 자동 생성한 경로는 걸으면서 기록한 뒤 공유해 주세요.")


def preview_public(walk: SavedWalk, radius_m: int) -> dict:
    """공유하기 전에 실제로 공개될 경로를 보여 준다. 저장하지 않는다."""
    _check_shareable(walk)
    points = public_route(walk, radius_m)
    values = _public_values(walk, points, radius_m)
    return {
        "saved_walk_id": walk.id,
        "hide_radius_m": radius_m,
        "hidden_m": max(0.0, round(walk.distance_m - values["distance_m"], 1)),
        "region": suggest_region(values["start_lat"], values["start_lng"]),
        "route": route_segments(points),
        "can_navigate": can_navigate(points),
        **{key: values[key] for key in ("distance_m", "estimated_min", "elevation_gain_m", "difficulty", "start_label", "end_label")},
    }


# ---------- 권한
def can_view(trail: CommunityTrail, viewer: User | None) -> bool:
    return trail.visibility == "public" or (viewer is not None and trail.user_id == viewer.id)


def course_open_to(db: Session, course: WalkingCourse, viewer: User | None) -> bool:
    """커뮤니티 코스는 산책길이 공개인 동안 누구나, 비공개면 주인만 볼 수 있다."""
    trail = db.get(CommunityTrail, course.community_trail_id)
    return trail is not None and can_view(trail, viewer)


# ---------- 공유, 수정, 해제
def create_trail(db: Session, user: User, walk: SavedWalk, body: schemas.TrailCreate, now: datetime) -> CommunityTrail:
    _check_shareable(walk)
    if walk.community_trail is not None:
        raise CommunityError(409, "이미 공유한 산책길이에요. 내 산책길 관리에서 고칠 수 있어요.")
    same_route = db.scalar(
        select(CommunityTrail.id).join(SavedWalk, CommunityTrail.saved_walk_id == SavedWalk.id).where(CommunityTrail.user_id == user.id, SavedWalk.route_hash == walk.route_hash).limit(1)
    )
    if same_route is not None:
        raise CommunityError(409, "같은 경로를 이미 공유했어요.")
    _check_cover(walk, body.cover_photo_id)
    values = _public_values(walk, public_route(walk, body.hide_radius_m), body.hide_radius_m)
    trail = CommunityTrail(
        user_id=user.id,
        saved_walk_id=walk.id,
        title=body.title,
        description=body.description,
        cover_photo_id=body.cover_photo_id,
        visibility=body.visibility,
        region=body.region or suggest_region(values["start_lat"], values["start_lng"]),
        features=sorted(set(body.features)),
        suitable_for=sorted(set(body.suitable_for)),
        hide_radius_m=body.hide_radius_m,
        created_at=now,
        updated_at=now,
        **values,
    )
    db.add(trail)
    try:
        db.commit()
    except IntegrityError as error:
        # 공유 버튼을 두 번 눌러 같은 요청이 동시에 들어온 경우다.
        db.rollback()
        raise CommunityError(409, "이미 공유한 산책길이에요. 내 산책길 관리에서 고칠 수 있어요.") from error
    return trail


def _check_cover(walk: SavedWalk, photo_id: int | None) -> None:
    if photo_id is not None and photo_id not in {photo.id for photo in walk.photos}:
        raise CommunityError(422, "이 산책길에 올린 사진만 대표 이미지로 고를 수 있어요.")


def update_trail(db: Session, trail: CommunityTrail, changes: dict) -> CommunityTrail:
    if "cover_photo_id" in changes:
        _check_cover(trail.walk, changes["cover_photo_id"])
    radius = changes.pop("hide_radius_m", None)
    if radius is not None and radius != trail.hide_radius_m:
        for key, value in _public_values(trail.walk, public_route(trail.walk, radius), radius).items():
            setattr(trail, key, value)
        trail.hide_radius_m = radius
    if not changes.get("region", True):
        changes["region"] = suggest_region(trail.start_lat, trail.start_lng)
    for key in ("features", "suitable_for"):
        if key in changes:
            changes[key] = sorted(set(changes[key]))
    for key, value in changes.items():
        setattr(trail, key, value)
    _sync_course(db, trail)
    db.commit()
    return trail


def delete_trail(db: Session, trail: CommunityTrail) -> None:
    """공유를 해제한다. 원본 산책길은 그대로 두고 좋아요, 저장, 후기는 함께 지운다."""
    _retire_course(db, trail)
    db.delete(trail)
    db.commit()


def before_walk_deleted(db: Session, walk: SavedWalk) -> None:
    """원본 산책길을 지우면 공유한 글도 cascade로 지워지므로 코스 연결을 먼저 끊는다."""
    if walk.community_trail is not None:
        _retire_course(db, walk.community_trail)


def clear_cover(db: Session, photo: SavedWalkPhoto) -> None:
    """대표 이미지로 쓰던 사진을 지웠을 때. SQLite는 외래 키를 강제하지 않아 직접 비운다."""
    db.execute(update(CommunityTrail).where(CommunityTrail.cover_photo_id == photo.id).values(cover_photo_id=None))


def count_view(db: Session, trail: CommunityTrail, viewer: User | None) -> None:
    """주인이 보는 것은 세지 않는다. 조회수는 수정 시각을 바꾸지 않는다."""
    if viewer is not None and viewer.id == trail.user_id:
        return
    db.execute(
        update(CommunityTrail)
        .where(CommunityTrail.id == trail.id)
        .values(view_count=CommunityTrail.view_count + 1, updated_at=CommunityTrail.updated_at)
        .execution_options(synchronize_session=False)
    )
    db.commit()


# ---------- 길 안내
def _course_of(db: Session, trail: CommunityTrail) -> WalkingCourse | None:
    return db.scalar(select(WalkingCourse).where(WalkingCourse.community_trail_id == trail.id))


def _course_values(trail: CommunityTrail) -> dict:
    route = simplify(join_points(trail_points(trail)))
    attributes, unknown = course_attributes(None, recorded=False)
    facilities = nearby_facilities(route)
    return {
        "name": trail.title[:80],
        "description": "커뮤니티에 공유된 산책길이에요.",
        "area": trail.region,
        "start_lat": route[0][0],
        "start_lng": route[0][1],
        "distance_km": round(route_km(route), 2),
        "duration_min": trail.estimated_min,
        "route": route,
        "park_names": sorted({facility["name"] for facility in facilities if facility["type"] == "park" and facility["name"]}),
        "pet_allowed": True,
        "pet_rule_note": PET_RULE,
        "facilities": facilities,
        "environment": None,
        "data_sources": {"route": "커뮤니티 산책길(출발점과 도착점 주변을 가린 경로)", "source_type": "community", "environment_status": "off", "team_estimates": [], "unknown": unknown},
        "owner_user_id": trail.user_id,
        "is_active": False,
        **attributes,
    }


def start_course(db: Session, trail: CommunityTrail) -> WalkingCourse:
    """이 산책길의 길 안내 코스. 산책길마다 하나만 만들어 함께 쓴다. 추천 후보에는 들어가지 않는다."""
    course = _course_of(db, trail)
    if course is not None:
        return course
    try:
        values = _course_values(trail)
    except CourseError as error:
        raise CommunityError(422, "가린 구간이나 끊긴 구간 때문에 한 줄로 이을 수 없어 길 안내를 할 수 없어요. 지도와 GPX로 확인해 주세요.") from error
    # SQLite는 지운 번호를 다시 쓰므로 번호만으로는 예전 코스와 겹칠 수 있다.
    course = WalkingCourse(code=f"trail-{trail.id}-{secrets.token_hex(4)}", community_trail_id=trail.id, **values)
    db.add(course)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        course = _course_of(db, trail)
        if course is None:
            raise
    return course


def _sync_course(db: Session, trail: CommunityTrail) -> None:
    course = _course_of(db, trail)
    if course is None:
        return
    try:
        values = _course_values(trail)
    except CourseError:
        _retire_course(db, trail)
        return
    for key, value in values.items():
        setattr(course, key, value)


def _retire_course(db: Session, trail: CommunityTrail) -> None:
    course = _course_of(db, trail)
    if course is None:
        return
    for key, value in RETIRED_COURSE.items():
        setattr(course, key, value)
    db.flush()


def user_delete_statements(user_id: int) -> tuple:
    """탈퇴할 때 지울 커뮤니티 행. 내 산책길의 좋아요, 저장, 후기와 내가 남긴 것을 모두 지운다.

    계정 삭제는 ORM을 거치지 않으므로 cascade가 동작하지 않는다. 가리키는 쪽부터 지운다.
    """
    trails = select(CommunityTrail.id).where(CommunityTrail.user_id == user_id)
    reviews = select(TrailReview.id).where(or_(TrailReview.user_id == user_id, TrailReview.community_trail_id.in_(trails)))
    return (
        update(WalkingCourse).where(WalkingCourse.community_trail_id.in_(trails)).values(**RETIRED_COURSE),
        delete(TrailReviewPhoto).where(TrailReviewPhoto.review_id.in_(reviews)),
        delete(TrailReview).where(TrailReview.id.in_(reviews)),
        delete(TrailLike).where(or_(TrailLike.user_id == user_id, TrailLike.community_trail_id.in_(trails))),
        delete(TrailBookmark).where(or_(TrailBookmark.user_id == user_id, TrailBookmark.community_trail_id.in_(trails))),
        delete(CommunityTrail).where(CommunityTrail.user_id == user_id),
    )


# ---------- 목록과 집계
_LIKES = select(TrailLike.community_trail_id.label("trail_id"), func.count().label("total")).group_by(TrailLike.community_trail_id).subquery("like_totals")
_BOOKMARKS = select(TrailBookmark.community_trail_id.label("trail_id"), func.count().label("total")).group_by(TrailBookmark.community_trail_id).subquery("bookmark_totals")
_REVIEWS = (
    select(TrailReview.community_trail_id.label("trail_id"), func.count().label("total"), func.sum(TrailReview.rating).label("rating_sum"), func.avg(TrailReview.rating).label("rating_avg"))
    .group_by(TrailReview.community_trail_id)
    .subquery("review_totals")
)
_LIKE_COUNT = func.coalesce(_LIKES.c.total, 0)
_BOOKMARK_COUNT = func.coalesce(_BOOKMARKS.c.total, 0)
_REVIEW_COUNT = func.coalesce(_REVIEWS.c.total, 0)
_POPULARITY = (
    _LIKE_COUNT * POPULARITY_WEIGHTS["like"]
    + _BOOKMARK_COUNT * POPULARITY_WEIGHTS["bookmark"]
    + _REVIEW_COUNT * POPULARITY_WEIGHTS["review"]
    + CommunityTrail.view_count * POPULARITY_WEIGHTS["view"]
)
_WEIGHTED_RATING = case(
    (_REVIEW_COUNT > 0, (RATING_PRIOR * RATING_PRIOR_COUNT + func.coalesce(_REVIEWS.c.rating_sum, 0)) * 1.0 / (RATING_PRIOR_COUNT + _REVIEW_COUNT)),
    else_=0.0,
)
_TRAIL_ROWS = (
    select(
        CommunityTrail,
        User.name.label("author_name"),
        _LIKE_COUNT.label("like_count"),
        _BOOKMARK_COUNT.label("bookmark_count"),
        _REVIEW_COUNT.label("review_count"),
        _REVIEWS.c.rating_avg.label("average_rating"),
    )
    .join(User, CommunityTrail.user_id == User.id)
    .outerjoin(_LIKES, _LIKES.c.trail_id == CommunityTrail.id)
    .outerjoin(_BOOKMARKS, _BOOKMARKS.c.trail_id == CommunityTrail.id)
    .outerjoin(_REVIEWS, _REVIEWS.c.trail_id == CommunityTrail.id)
)
_SORTS = {
    "recent": (CommunityTrail.created_at.desc(), CommunityTrail.id.desc()),
    "popular": (_POPULARITY.desc(), CommunityTrail.id.desc()),
    "rating": (_WEIGHTED_RATING.desc(), _REVIEW_COUNT.desc(), CommunityTrail.id.desc()),
}
_IS_PUBLIC = CommunityTrail.visibility == "public"


def _summaries(db: Session, rows: list, viewer: User | None) -> list[dict]:
    """보는 사람 기준의 카드 값. 원본 산책길의 이름, 메모, 시각, 공유 토큰은 넣지 않는다."""
    ids = [row.CommunityTrail.id for row in rows]
    liked: set[int] = set()
    bookmarked: set[int] = set()
    if viewer is not None and ids:
        liked = set(db.scalars(select(TrailLike.community_trail_id).where(TrailLike.user_id == viewer.id, TrailLike.community_trail_id.in_(ids))))
        bookmarked = set(db.scalars(select(TrailBookmark.community_trail_id).where(TrailBookmark.user_id == viewer.id, TrailBookmark.community_trail_id.in_(ids))))
    return [
        {
            "id": row.CommunityTrail.id,
            "title": row.CommunityTrail.title,
            "description": row.CommunityTrail.description,
            "region": row.CommunityTrail.region,
            "author_name": row.author_name,
            "cover_photo_id": row.CommunityTrail.cover_photo_id,
            "visibility": row.CommunityTrail.visibility,
            "features": row.CommunityTrail.features,
            "suitable_for": row.CommunityTrail.suitable_for,
            "distance_m": row.CommunityTrail.distance_m,
            "estimated_min": row.CommunityTrail.estimated_min,
            "elevation_gain_m": row.CommunityTrail.elevation_gain_m,
            "difficulty": row.CommunityTrail.difficulty,
            "preview": row.CommunityTrail.preview,
            "view_count": row.CommunityTrail.view_count,
            "like_count": row.like_count,
            "bookmark_count": row.bookmark_count,
            "review_count": row.review_count,
            "average_rating": None if row.average_rating is None else round(float(row.average_rating), 1),
            "liked": row.CommunityTrail.id in liked,
            "bookmarked": row.CommunityTrail.id in bookmarked,
            "is_mine": viewer is not None and row.CommunityTrail.user_id == viewer.id,
            "created_at": row.CommunityTrail.created_at,
            "updated_at": row.CommunityTrail.updated_at,
        }
        for row in rows
    ]


def _page(db: Session, query, conditions: list, order: tuple, count_query, page: int, size: int, viewer: User | None) -> dict:
    total = db.scalar(count_query) or 0
    rows = list(db.execute(query.where(*conditions).order_by(*order).limit(size).offset((page - 1) * size)))
    return {"items": _summaries(db, rows, viewer), "total": total, "page": page, "size": size, "has_next": page * size < total}


def list_trails(db: Session, viewer: User | None, filters: schemas.TrailFilters, page: int, size: int) -> dict:
    conditions = [_IS_PUBLIC]
    if filters.q:
        conditions.append(or_(CommunityTrail.title.icontains(filters.q, autoescape=True), CommunityTrail.region.icontains(filters.q, autoescape=True), CommunityTrail.description.icontains(filters.q, autoescape=True)))
    if filters.region:
        conditions.append(CommunityTrail.region == filters.region)
    if filters.min_km is not None:
        conditions.append(CommunityTrail.distance_m >= filters.min_km * 1000)
    if filters.max_km is not None:
        conditions.append(CommunityTrail.distance_m < filters.max_km * 1000)
    if filters.min_minutes is not None:
        conditions.append(CommunityTrail.estimated_min >= filters.min_minutes)
    if filters.max_minutes is not None:
        conditions.append(CommunityTrail.estimated_min < filters.max_minutes)
    if filters.difficulty:
        conditions.append(CommunityTrail.difficulty == filters.difficulty)
    # 태그 값은 스키마가 정해진 목록으로 검증했다. JSON 비교 문법이 DB마다 달라 문자열로 찾는다.
    if filters.suitable:
        conditions.append(cast(CommunityTrail.suitable_for, String).like(f'%"{filters.suitable}"%'))
    if filters.feature:
        conditions.append(cast(CommunityTrail.features, String).like(f'%"{filters.feature}"%'))
    count_query = select(func.count(CommunityTrail.id)).where(*conditions)
    return _page(db, _TRAIL_ROWS, conditions, _SORTS[filters.sort], count_query, page, size, viewer)


def list_regions(db: Session) -> list[dict]:
    rows = db.execute(select(CommunityTrail.region, func.count(CommunityTrail.id)).where(_IS_PUBLIC).group_by(CommunityTrail.region).order_by(func.count(CommunityTrail.id).desc(), CommunityTrail.region))
    return [{"region": region, "count": count} for region, count in rows]


def nearby_trails(db: Session, viewer: User | None, latitude: float, longitude: float, radius_km: float, limit: int) -> list[dict]:
    """가린 뒤의 출발점이 가까운 순서. 위치는 저장하지 않는다."""
    lat_span = radius_km / 110.54
    lng_span = radius_km / (111.32 * max(0.01, math.cos(math.radians(latitude))))
    rows = list(
        db.execute(
            _TRAIL_ROWS.where(
                _IS_PUBLIC,
                CommunityTrail.start_lat.between(latitude - lat_span, latitude + lat_span),
                CommunityTrail.start_lng.between(longitude - lng_span, longitude + lng_span),
            )
        )
    )
    distances = {row.CommunityTrail.id: haversine_m(latitude, longitude, row.CommunityTrail.start_lat, row.CommunityTrail.start_lng) for row in rows}
    inside = sorted((row for row in rows if distances[row.CommunityTrail.id] <= radius_km * 1000), key=lambda row: distances[row.CommunityTrail.id])[:limit]
    return [{**item, "distance_from_me_m": round(distances[item["id"]], -1)} for item in _summaries(db, inside, viewer)]


def _pet_tags(pet: Pet, life_stage: str) -> set[str]:
    tags = {pet.size}
    if life_stage in ("senior", "puppy"):
        tags.add(life_stage)
    if pet.activity_level == "high":
        tags.add("active")
    if pet.personality == "timid" or pet.novelty_reaction == "anxious":
        tags.add("timid")
    return tags


def _taste_fit(weights: dict, trail: CommunityTrail) -> float:
    """피드백으로 학습한 코스 특성 가중치를 쓴다. 표시되지 않은 특성은 모르는 값이라 계산에서 뺀다."""
    km = trail.distance_m / 1000
    vector = {FEATURE_TO_ATTRIBUTE[tag]: 1.0 for tag in trail.features if tag in FEATURE_TO_ATTRIBUTE}
    vector["short"] = 1.0 if km <= 2.0 else 0.0
    vector["long"] = 1.0 if km >= 3.5 else 0.0
    vector["hill"] = HILL_BY_DIFFICULTY[trail.difficulty]
    return max(0.0, min(1.0, 0.5 + sum((weights or {}).get(key, 0.0) * (value - 0.5) for key, value in vector.items())))


def score_for_pet(trail: CommunityTrail, pet: Pet, features, review_count: int, rating_avg: float | None) -> tuple[float, list[str]]:
    """반려동물에게 맞는 정도(0~1)와 그 근거. 근거에는 실제 값과 보호자가 표시한 값만 쓴다."""
    km = trail.distance_m / 1000
    target = features.preferred_distance_km or features.ideal_distance_km
    distance_fit = max(0.0, 1 - abs(km - target) / max(target, 0.5))

    tags = _pet_tags(pet, features.life_stage)
    declared = set(trail.suitable_for)
    matched = sorted(tags & declared)
    suitable_fit = 0.5 if not declared else 1.0 if matched else 0.25

    terrain_fit = {"easy": 1.0, "moderate": 0.5 + features.hill_tolerance / 2, "hard": features.hill_tolerance}[trail.difficulty]
    if rating_avg is None:
        quality = 0.5
    else:
        weighted = (RATING_PRIOR * RATING_PRIOR_COUNT + rating_avg * review_count) / (RATING_PRIOR_COUNT + review_count)
        quality = (weighted - 1) / 4

    score = (
        RECOMMEND_WEIGHTS["distance"] * distance_fit
        + RECOMMEND_WEIGHTS["suitable"] * suitable_fit
        + RECOMMEND_WEIGHTS["terrain"] * terrain_fit
        + RECOMMEND_WEIGHTS["taste"] * _taste_fit(pet.learned_attribute_weights, trail)
        + RECOMMEND_WEIGHTS["quality"] * quality
    )
    reasons = []
    if distance_fit >= 0.6:
        reasons.append(f"{pet.name}에게 권장하는 {target:.1f}km와 비슷한 {km:.1f}km예요")
    if matched:
        reasons.append(f"공유한 보호자가 {SUITABLE_LABELS[matched[0]]}에게 추천했어요")
    if pet.heat_sensitivity == "high" and "shade" in trail.features:
        reasons.append("더위를 많이 타는 아이에게 좋은 그늘이 있다고 표시됐어요")
    if rating_avg is not None and rating_avg >= 4:
        reasons.append(f"평점 {rating_avg:.1f}점, 후기 {review_count}개예요")
    return score, reasons


def recommend_trails(db: Session, viewer: User | None, pet: Pet, limit: int) -> list[dict]:
    """공개 산책길 중 이 반려동물에게 맞는 순서. 내가 공유한 길은 뺀다."""
    features = build_features(to_profile(pet))
    query = _TRAIL_ROWS.where(_IS_PUBLIC)
    if viewer is not None:
        query = query.where(CommunityTrail.user_id != viewer.id)
    rows = list(db.execute(query.order_by(*_SORTS["recent"]).limit(RECOMMEND_CANDIDATES)))
    scored = []
    for row in rows:
        average = None if row.average_rating is None else float(row.average_rating)
        score, reasons = score_for_pet(row.CommunityTrail, pet, features, row.review_count, average)
        scored.append((score, row, reasons))
    scored.sort(key=lambda item: (-item[0], -item[1].CommunityTrail.id))
    top = scored[:limit]
    summaries = _summaries(db, [row for _, row, _ in top], viewer)
    return [{**summary, "match_score": round(score * 100), "reasons": reasons} for summary, (score, _, reasons) in zip(summaries, top)]


def trail_detail(db: Session, trail: CommunityTrail, viewer: User | None) -> dict:
    row = db.execute(_TRAIL_ROWS.where(CommunityTrail.id == trail.id)).one()
    summary = _summaries(db, [row], viewer)[0]
    points = trail_points(trail)
    segments = route_segments(points)
    my_review = None
    walked = False
    if viewer is not None:
        review = db.scalar(select(TrailReview).where(TrailReview.community_trail_id == trail.id, TrailReview.user_id == viewer.id))
        my_review = review_items(db, [review], viewer)[0] if review else None
        walked = (trail.id, viewer.id) in _verified_pairs(db, [trail.id], [viewer.id])
    mine = summary["is_mine"]
    return {
        **summary,
        "route": segments,
        "start": segments[0][0],
        "end": segments[-1][-1],
        "start_label": trail.start_label,
        "end_label": trail.end_label,
        "can_navigate": can_navigate(points),
        "my_review": my_review,
        "walked": walked,
        # 주인에게만 보여 준다. 가리는 반경을 알면 경로가 끊긴 곳으로 원본 출발점을 되짚을 수 있다.
        "owner": {"saved_walk_id": trail.saved_walk_id, "hide_radius_m": trail.hide_radius_m} if mine else None,
    }


def set_reaction(db: Session, model: type[TrailLike] | type[TrailBookmark], user: User, trail: CommunityTrail, on: bool) -> int:
    """좋아요와 저장. 여러 번 눌러도 결과가 같고, 고유 제약이 동시 요청의 중복도 막는다. 지금의 총수를 돌려준다."""
    existing = db.scalar(select(model).where(model.user_id == user.id, model.community_trail_id == trail.id))
    if on and existing is None:
        db.add(model(user_id=user.id, community_trail_id=trail.id, created_at=now_local()))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    elif not on and existing is not None:
        db.delete(existing)
        db.commit()
    return db.scalar(select(func.count()).select_from(model).where(model.community_trail_id == trail.id)) or 0


# ---------- 내 활동
def my_trails(db: Session, user: User, page: int, size: int) -> dict:
    conditions = [CommunityTrail.user_id == user.id]
    return _page(db, _TRAIL_ROWS, conditions, _SORTS["recent"], select(func.count(CommunityTrail.id)).where(*conditions), page, size, user)


def my_reactions(db: Session, model: type[TrailLike] | type[TrailBookmark], user: User, page: int, size: int) -> dict:
    """내가 저장하거나 좋아요한 길. 작성자가 비공개로 돌린 길은 숨기고, 다시 공개하면 돌아오도록 행은 남긴다."""
    viewable = or_(_IS_PUBLIC, CommunityTrail.user_id == user.id)
    conditions = [model.user_id == user.id, viewable]
    query = _TRAIL_ROWS.join(model, model.community_trail_id == CommunityTrail.id)
    count_query = select(func.count(model.id)).join(CommunityTrail, model.community_trail_id == CommunityTrail.id).where(*conditions)
    result = _page(db, query, conditions, (model.created_at.desc(), model.id.desc()), count_query, page, size, user)
    hidden = select(func.count(model.id)).join(CommunityTrail, model.community_trail_id == CommunityTrail.id).where(model.user_id == user.id, ~viewable)
    return {**result, "hidden_count": db.scalar(hidden) or 0}


# ---------- 후기
def _verified_pairs(db: Session, trail_ids: list[int], user_ids: list[int]) -> set[tuple[int, int]]:
    """(산책길, 보호자) 중 이 산책길의 코스를 GPS로 걸은 기록이 있는 쌍. 시연용 걷기와 직접 입력은 세지 않는다."""
    if not trail_ids or not user_ids:
        return set()
    rows = db.execute(
        select(WalkingCourse.community_trail_id, Pet.user_id)
        .join(WalkHistory, WalkHistory.course_id == WalkingCourse.id)
        .join(Pet, WalkHistory.pet_id == Pet.id)
        .where(
            WalkingCourse.community_trail_id.in_(trail_ids),
            Pet.user_id.in_(user_ids),
            WalkHistory.tracking_source == "gps",
            func.coalesce(WalkHistory.distance_km, WalkingCourse.distance_km) >= WalkingCourse.distance_km * VERIFIED_SHARE,
        )
        .distinct()
    )
    return {(trail_id, user_id) for trail_id, user_id in rows}


def review_items(db: Session, reviews: list[TrailReview], viewer: User | None) -> list[dict]:
    pairs = _verified_pairs(db, sorted({review.community_trail_id for review in reviews}), sorted({review.user_id for review in reviews}))
    return [
        {
            "id": review.id,
            "trail_id": review.community_trail_id,
            "rating": review.rating,
            "content": review.content,
            "author_name": review.author.name,
            "is_mine": viewer is not None and review.user_id == viewer.id,
            "verified": (review.community_trail_id, review.user_id) in pairs,
            "edited": review.updated_at != review.created_at,
            "photos": [{"id": photo.id} for photo in review.photos],
            "created_at": review.created_at,
            "updated_at": review.updated_at,
        }
        for review in reviews
    ]


def list_reviews(db: Session, trail: CommunityTrail, viewer: User | None, page: int, size: int) -> dict:
    total = db.scalar(select(func.count(TrailReview.id)).where(TrailReview.community_trail_id == trail.id)) or 0
    reviews = list(db.scalars(select(TrailReview).where(TrailReview.community_trail_id == trail.id).order_by(TrailReview.id.desc()).limit(size).offset((page - 1) * size)))
    return {"items": review_items(db, reviews, viewer), "total": total, "page": page, "size": size, "has_next": page * size < total}


def create_review(db: Session, user: User, trail: CommunityTrail, rating: int, content: str, now: datetime) -> TrailReview:
    """보호자 한 명이 산책길마다 하나만 남긴다. 평점이 부풀려지지 않게 내 산책길에는 남길 수 없다."""
    if trail.user_id == user.id:
        raise CommunityError(403, "내가 공유한 산책길에는 후기를 남길 수 없어요.")
    exists = db.scalar(select(TrailReview.id).where(TrailReview.community_trail_id == trail.id, TrailReview.user_id == user.id))
    if exists is not None:
        raise CommunityError(409, "이미 후기를 남겼어요. 남긴 후기를 고쳐 주세요.")
    review = TrailReview(user_id=user.id, community_trail_id=trail.id, rating=rating, content=content, created_at=now, updated_at=now)
    db.add(review)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise CommunityError(409, "이미 후기를 남겼어요. 남긴 후기를 고쳐 주세요.") from error
    return review


def update_review(db: Session, review: TrailReview, changes: dict, now: datetime) -> TrailReview:
    for key, value in changes.items():
        setattr(review, key, value)
    review.updated_at = now
    db.commit()
    return review


def my_reviews(db: Session, user: User, page: int, size: int) -> dict:
    """내가 쓴 후기. 작성자가 비공개로 돌린 길은 이름을 숨기되 내가 쓴 글은 고치거나 지울 수 있다."""
    total = db.scalar(select(func.count(TrailReview.id)).where(TrailReview.user_id == user.id)) or 0
    reviews = list(db.scalars(select(TrailReview).where(TrailReview.user_id == user.id).order_by(TrailReview.id.desc()).limit(size).offset((page - 1) * size)))
    items = []
    for item, review in zip(review_items(db, reviews, user), reviews):
        available = can_view(review.trail, user)
        items.append({**item, "trail_available": available, "trail_title": review.trail.title if available else None})
    return {"items": items, "total": total, "page": page, "size": size, "has_next": page * size < total}
