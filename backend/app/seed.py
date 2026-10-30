"""초기 데이터: 산책 코스, 기본 보호자, 시연용 반려동물."""
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Pet, User, WalkingCourse

COURSES_PATH = Path(__file__).parent / "data" / "courses.json"
DEFAULT_USER_ID = 1


def seed_courses(db: Session) -> None:
    """코드 기준으로 코스를 추가하거나 갱신한다. 다시 실행해도 안전하다."""
    existing = {course.code: course for course in db.scalars(select(WalkingCourse))}
    for raw in json.loads(COURSES_PATH.read_text(encoding="utf-8")):
        course = existing.get(raw["code"])
        if course is None:
            db.add(WalkingCourse(**raw))
        else:
            for key, value in raw.items():
                setattr(course, key, value)


def seed_default_user(db: Session) -> User:
    user = db.get(User, DEFAULT_USER_ID)
    if user is None:
        user = User(
            id=DEFAULT_USER_ID,
            name="보호자",
            available_windows=[{"start_hour": 16, "end_hour": 20}],
            preferred_duration_min=40,
            walks_per_day=1,
        )
        db.add(user)
    return user


def seed_demo_pet(db: Session, user: User) -> None:
    if db.scalar(select(Pet.id).limit(1)) is not None:
        return
    db.add(
        Pet(
            user_id=user.id,
            name="두부",
            breed="말티즈",
            age_years=5,
            weight_kg=4.2,
            size="small",
            activity_level="medium",
            personality="timid",
            path_preference="familiar",
            heat_sensitivity="medium",
            novelty_reaction="anxious",
        )
    )


def seed_all(db: Session) -> None:
    seed_courses(db)
    user = seed_default_user(db)
    db.flush()
    if get_settings().seed_demo_pet:
        seed_demo_pet(db, user)
    db.commit()
