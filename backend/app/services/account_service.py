"""계정 탈퇴와 데이터 삭제.

되돌릴 수 없는 삭제이므로 유예 기간 없이 바로 지운다. 탈퇴 기록은 DB 밖 파일에 남겨,
백업에서 복구해도 탈퇴한 보호자가 되살아나지 않게 한다(backup_service.restore_backup).
"""
import json
import logging
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    AuthSession,
    CommunityTrail,
    Pet,
    PetCoursePreference,
    Recommendation,
    SavedWalk,
    SavedWalkPhoto,
    SavedWalkPoint,
    TrailReview,
    User,
    WalkFeedback,
    WalkHistory,
    WalkingCourse,
)
from app.services import auth_service, community_service

LEDGER_NAME = "deletions.jsonl"
logger = logging.getLogger(__name__)


class AccountError(Exception):
    """화면에 그대로 보여 줄 수 있는 탈퇴 실패 이유."""


def data_counts(db: Session, user_id: int) -> dict[str, int]:
    pets = select(Pet.id).where(Pet.user_id == user_id)
    walks = select(SavedWalk.id).where(SavedWalk.user_id == user_id)

    def count(model, condition) -> int:
        return db.scalar(select(func.count()).select_from(model).where(condition)) or 0

    return {
        "pets": count(Pet, Pet.user_id == user_id),
        "walks": count(WalkHistory, WalkHistory.pet_id.in_(pets)),
        "feedback": count(WalkFeedback, WalkFeedback.pet_id.in_(pets)),
        "recommendations": count(Recommendation, Recommendation.pet_id.in_(pets)),
        "saved_walks": count(SavedWalk, SavedWalk.user_id == user_id),
        "photos": count(SavedWalkPhoto, SavedWalkPhoto.walk_id.in_(walks)),
        "personal_courses": count(WalkingCourse, WalkingCourse.owner_user_id == user_id),
        "shared_walks": count(SavedWalk, (SavedWalk.user_id == user_id) & (SavedWalk.visibility != "private")),
        "community_trails": count(CommunityTrail, CommunityTrail.user_id == user_id),
        "trail_reviews": count(TrailReview, TrailReview.user_id == user_id),
    }


def delete_user_data(db: Session, user_id: int) -> None:
    """보호자와 보호자에게 딸린 행을 모두 지운다. 커밋은 호출한 쪽이 한다.

    외래 키를 켠 DB에서도 동작하도록 가리키는 쪽부터 지운다. 공유 링크와 공개 목록은 산책길과 함께 사라진다.
    """
    pets = select(Pet.id).where(Pet.user_id == user_id)
    walks = select(SavedWalk.id).where(SavedWalk.user_id == user_id)
    for statement in (
        *community_service.user_delete_statements(user_id),
        delete(WalkFeedback).where(WalkFeedback.pet_id.in_(pets)),
        delete(PetCoursePreference).where(PetCoursePreference.pet_id.in_(pets)),
        delete(WalkHistory).where(WalkHistory.pet_id.in_(pets)),
        delete(Recommendation).where(Recommendation.pet_id.in_(pets)),
        delete(SavedWalkPhoto).where(SavedWalkPhoto.walk_id.in_(walks)),
        delete(SavedWalkPoint).where(SavedWalkPoint.walk_id.in_(walks)),
        delete(WalkingCourse).where(WalkingCourse.owner_user_id == user_id),
        delete(SavedWalk).where(SavedWalk.user_id == user_id),
        delete(Pet).where(Pet.user_id == user_id),
        delete(AuthSession).where(AuthSession.user_id == user_id),
        delete(User).where(User.id == user_id),
    ):
        db.execute(statement, execution_options={"synchronize_session": False})


def record_deletion(directory: Path, user_id: int, created_at: datetime, deleted_at: datetime) -> None:
    """탈퇴 기록을 남긴다. 아이디, 이름, 이메일은 넣지 않는다.

    SQLite는 지운 번호를 다시 쓸 수 있어, 같은 번호의 새 계정과 구분하도록 가입 시각을 함께 둔다.
    """
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    line = json.dumps({"user_id": user_id, "user_created_at": created_at.isoformat(), "deleted_at": deleted_at.isoformat()})
    descriptor = os.open(directory / LEDGER_NAME, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as ledger:
        ledger.write(line + "\n")
        ledger.flush()
        os.fsync(ledger.fileno())


def read_deletions(directory: Path) -> list[dict]:
    path = directory / LEDGER_NAME
    if not path.exists():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            # 쓰다가 전원이 나가 끊긴 줄이다. 나머지 기록은 그대로 쓴다.
            logger.warning("탈퇴 기록에서 읽을 수 없는 줄을 건너뜀")
    return entries


def replay_deletions(db: Session, entries: list[dict]) -> int:
    """백업에서 되살아난 탈퇴 계정을 다시 지우고 지운 수를 돌려준다. 커밋은 호출한 쪽이 한다."""
    removed = 0
    for entry in entries:
        created_at = datetime.fromisoformat(entry["user_created_at"])
        user_id = db.scalar(select(User.id).where(User.id == entry["user_id"], User.created_at == created_at))
        if user_id is not None:
            delete_user_data(db, user_id)
            removed += 1
    return removed


def delete_account(db: Session, user: User, settings: Settings, now: datetime) -> None:
    """탈퇴 처리. 탈퇴 기록을 먼저 남기고 커밋해, 지워졌는데 기록이 없어 복구 때 되살아나는 일을 막는다."""
    login_id, user_id, created_at = user.login_id, user.id, user.created_at
    delete_user_data(db, user_id)
    try:
        record_deletion(Path(settings.backup_dir), user_id, created_at, now)
    except OSError as error:
        if settings.backup_enabled:
            db.rollback()
            logger.error("탈퇴 기록을 남기지 못해 탈퇴를 취소함: %s", type(error).__name__)
            raise AccountError("탈퇴를 처리하지 못했어요. 지운 데이터는 없으니 잠시 뒤 다시 시도해 주세요.") from error
        logger.warning("백업을 쓰지 않아 탈퇴 기록 없이 진행함: %s", type(error).__name__)
    db.commit()
    if login_id:
        auth_service.throttle.clear(login_id)
    auth_service.throttle.clear(f"reauth:{user_id}")
