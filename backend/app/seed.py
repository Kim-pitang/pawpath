"""초기 데이터: 산책 코스, 기본 보호자, 시연용 반려동물."""
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Pet, User, WalkingCourse
from app.services.profile_service import new_default_profile

DATA_DIR = Path(__file__).parent / "data"
# 모든 지역의 코스를 넣어 두고 SERVICE_AREA로 고른다. 지역을 바꿔도 코스 번호와 기록이 유지된다.
# courses_gpx.json은 공개 GPX로 만든 코스로, app.gpx_import가 만든다. is_active가 없어 관리자가 끈 코스는 꺼진 채 남는다.
COURSE_FILES = (DATA_DIR / "courses.json", DATA_DIR / "courses_gaepo.json", DATA_DIR / "courses_gpx.json")
DEFAULT_USER_ID = 1


def new_user_defaults() -> dict:
    """시연 보호자와 새로 가입한 보호자가 함께 쓰는 기본 일정."""
    return {"available_windows": [{"start_hour": 16, "end_hour": 20}], "preferred_duration_min": 40, "walks_per_day": 1}


def seed_courses(db: Session) -> None:
    """코드 기준으로 코스를 추가하거나 갱신한다. 다시 실행해도 안전하다."""
    existing = {course.code: course for course in db.scalars(select(WalkingCourse))}
    for path in COURSE_FILES:
        if not path.exists():
            continue
        for raw in json.loads(path.read_text(encoding="utf-8")):
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
            **new_user_defaults(),
        )
        new_default_profile(user)
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
