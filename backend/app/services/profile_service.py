"""대표 계정 안의 프로필. 로그인과 데이터의 주인은 대표 계정(User)이고, 프로필은 그 안에서 누가 했는지를 구분한다."""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models import AuthSession, Pet, Profile, SavedWalk, User, WalkHistory
from app.services.report_service import is_simulated, walked_km

# 대표 프로필을 포함한 수다.
MAX_PROFILES = 5
# 요청마다 DB에 쓰지 않도록 마지막 이용 시각은 이 간격으로만 갱신한다.
TOUCH_MINUTES = 5
RECENT_WALKS = 10


class ProfileError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def new_default_profile(user: User) -> Profile:
    """대표 프로필. 계정을 만들 때 함께 만들고, 이름과 일정은 계정 값으로 시작한다."""
    return Profile(
        user=user,
        name=user.name[:30],
        is_default=True,
        available_windows=list(user.available_windows),
        preferred_duration_min=user.preferred_duration_min,
        walks_per_day=user.walks_per_day,
    )


def live_profiles(db: Session, user_id: int) -> list[Profile]:
    """지우지 않은 프로필. 대표 프로필이 먼저다."""
    query = select(Profile).where(Profile.user_id == user_id, Profile.deleted_at.is_(None)).order_by(Profile.is_default.desc(), Profile.id)
    return list(db.scalars(query))


def profiles_of(db: Session, user: User) -> list[Profile]:
    """계정의 프로필. 마이그레이션 밖에서 만든 계정처럼 대표 프로필이 없으면 만들어 늘 하나 이상 있게 한다."""
    profiles = live_profiles(db, user.id)
    if profiles:
        return profiles
    db.add(new_default_profile(user))
    try:
        db.commit()
    except IntegrityError:
        # 다른 요청이 먼저 만들었다. 계정마다 대표 프로필은 하나뿐이라 색인이 막는다.
        db.rollback()
    return live_profiles(db, user.id)


def selected_profile(db: Session, user_id: int, selected_id: int | None) -> Profile | None:
    """세션에 고른 프로필이 이 계정 소속이고 지워지지 않았을 때만 돌려준다. 프로필이 하나뿐이면 고르지 않아도 그 프로필이다."""
    if selected_id is not None:
        profile = db.get(Profile, selected_id)
        if profile is not None and profile.user_id == user_id and not profile.deleted:
            return profile
    profiles = live_profiles(db, user_id)
    return profiles[0] if len(profiles) == 1 else None


def family_profile(db: Session, user_id: int, profile_id: int, include_deleted: bool = False) -> Profile:
    """이 계정의 프로필을 돌려준다. 요청에 담긴 번호만으로는 권한을 인정하지 않으며, 다른 계정의 프로필은 없는 것과 같다."""
    profile = db.get(Profile, profile_id)
    if profile is None or profile.user_id != user_id or (profile.deleted and not include_deleted):
        raise ProfileError(404, "프로필을 찾을 수 없습니다")
    return profile


def _check_name(db: Session, user_id: int, name: str, editing: Profile | None = None) -> None:
    """가족 기록에서 누구의 것인지 이름으로 구분하므로 같은 이름을 쓰지 않는다."""
    if any(profile.name == name and profile is not editing for profile in live_profiles(db, user_id)):
        raise ProfileError(409, "같은 이름의 프로필이 있어요.")


def create_profile(db: Session, user: User, name: str, avatar_key: str) -> Profile:
    # 계정 행을 먼저 잠가 동시에 만들어도 개수 제한을 넘지 않게 한다.
    db.execute(update(User).where(User.id == user.id).values(updated_at=User.updated_at))
    profiles = live_profiles(db, user.id)
    if len(profiles) >= MAX_PROFILES:
        db.rollback()
        raise ProfileError(409, f"프로필은 대표 프로필을 포함해 {MAX_PROFILES}개까지 만들 수 있어요.")
    try:
        _check_name(db, user.id, name)
    except ProfileError:
        db.rollback()
        raise
    default = next((profile for profile in profiles if profile.is_default), None)
    profile = Profile(
        user_id=user.id,
        name=name,
        avatar_key=avatar_key,
        # 대표 프로필의 일정으로 시작하고 각자 고친다.
        available_windows=list(default.available_windows) if default else list(user.available_windows),
        preferred_duration_min=default.preferred_duration_min if default else user.preferred_duration_min,
        walks_per_day=default.walks_per_day if default else user.walks_per_day,
    )
    db.add(profile)
    db.commit()
    return profile


def update_profile(db: Session, profile: Profile, changes: dict) -> Profile:
    if "name" in changes:
        _check_name(db, profile.user_id, changes["name"], profile)
    for key, value in changes.items():
        setattr(profile, key, value)
    db.commit()
    return profile


def delete_profile(db: Session, profile: Profile, now: datetime) -> None:
    """프로필만 숨긴다. 산책 기록과 산책길은 그대로 남아 가족 기록에서 볼 수 있고, 반려동물은 가족 공용이라 영향이 없다."""
    if profile.is_default:
        raise ProfileError(409, "대표 프로필은 지울 수 없어요.")
    profile.deleted_at = now
    # 이 프로필을 쓰던 다른 기기의 세션은 다음 요청부터 프로필을 다시 고른다.
    db.execute(update(AuthSession).where(AuthSession.profile_id == profile.id).values(profile_id=None))
    db.commit()


def select_profile(db: Session, session: AuthSession, profile: Profile, now: datetime) -> None:
    session.profile_id = profile.id
    _touch(db, profile, now)
    db.commit()


def _touch(db: Session, profile: Profile, now: datetime) -> None:
    # 프로필 정보를 고친 시각과 구분하려고 수정 시각은 건드리지 않는다.
    db.execute(update(Profile).where(Profile.id == profile.id).values(last_active_at=now, updated_at=Profile.updated_at))
    profile.last_active_at = now


def touch(db: Session, profile: Profile, now: datetime) -> None:
    if profile.last_active_at is None or now - profile.last_active_at >= timedelta(minutes=TOUCH_MINUTES):
        _touch(db, profile, now)
        db.commit()


def can_manage(current: Profile, owner_profile_id: int | None) -> bool:
    """만든 프로필이나 대표 프로필만 고치고 지울 수 있다. 지운 프로필의 기록은 대표 프로필이 맡는다."""
    return current.is_default or current.id == owner_profile_id


@dataclass
class Activity:
    walk_count: int = 0
    total_distance_km: float = 0.0
    total_minutes: int = 0
    saved_walk_count: int = 0
    simulated_walk_count: int = 0
    last_walk_at: datetime | None = None

    def add_walk(self, walk: WalkHistory) -> None:
        # 시연용 산책은 다른 통계처럼 건수만 따로 센다.
        if is_simulated(walk):
            self.simulated_walk_count += 1
            return
        self.walk_count += 1
        self.total_distance_km = round(self.total_distance_km + walked_km(walk), 2)
        self.total_minutes += walk.duration_min
        if self.last_walk_at is None or walk.started_at > self.last_walk_at:
            self.last_walk_at = walk.started_at


@dataclass
class FamilyOverview:
    totals: Activity
    profile_count: int
    members: list[tuple[Profile, Activity]] = field(default_factory=list)
    pets: list[tuple[Pet, int]] = field(default_factory=list)
    recent_walks: list[WalkHistory] = field(default_factory=list)


def _family_walks(db: Session, user_id: int) -> list[WalkHistory]:
    query = select(WalkHistory).join(Pet, WalkHistory.pet_id == Pet.id).where(Pet.user_id == user_id).options(joinedload(WalkHistory.course)).order_by(WalkHistory.started_at.desc(), WalkHistory.id.desc())
    return list(db.scalars(query))


def _saved_walk_counts(db: Session, user_id: int) -> dict[int | None, int]:
    query = select(SavedWalk.profile_id, func.count(SavedWalk.id)).where(SavedWalk.user_id == user_id).group_by(SavedWalk.profile_id)
    return dict(db.execute(query).tuples().all())


def profile_activity(db: Session, profile: Profile) -> Activity:
    activity = Activity(saved_walk_count=_saved_walk_counts(db, profile.user_id).get(profile.id, 0))
    for walk in _family_walks(db, profile.user_id):
        if walk.profile_id == profile.id:
            activity.add_walk(walk)
    return activity


def family_overview(db: Session, user_id: int) -> FamilyOverview:
    """가족 전체 활동. 지운 프로필도 기록이 남아 있으면 함께 보여 줘 합계가 맞게 한다."""
    profiles = list(db.scalars(select(Profile).where(Profile.user_id == user_id).order_by(Profile.is_default.desc(), Profile.id)))
    saved_counts = _saved_walk_counts(db, user_id)
    walks = _family_walks(db, user_id)
    totals = Activity(saved_walk_count=sum(saved_counts.values()))
    by_profile: dict[int | None, Activity] = defaultdict(Activity)
    pet_walks: dict[int, int] = defaultdict(int)
    for walk in walks:
        totals.add_walk(walk)
        by_profile[walk.profile_id].add_walk(walk)
        if not is_simulated(walk):
            pet_walks[walk.pet_id] += 1
    members = []
    for profile in profiles:
        activity = by_profile[profile.id]
        activity.saved_walk_count = saved_counts.get(profile.id, 0)
        if not profile.deleted or activity.walk_count or activity.simulated_walk_count or activity.saved_walk_count:
            members.append((profile, activity))
    pets = list(db.scalars(select(Pet).where(Pet.user_id == user_id).order_by(Pet.id)))
    return FamilyOverview(
        totals=totals,
        profile_count=sum(1 for profile in profiles if not profile.deleted),
        members=members,
        pets=[(pet, pet_walks[pet.id]) for pet in pets],
        recent_walks=walks[:RECENT_WALKS],
    )
