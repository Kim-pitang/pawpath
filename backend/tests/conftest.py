"""테스트 공통 설정. 앱을 불러오기 전에 임시 DB와 Mock 날씨로 환경을 고정한다."""
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

_db_dir = tempfile.mkdtemp(prefix="pawpath-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_dir}/test.db"
os.environ["WEATHER_PROVIDER"] = "mock"
os.environ["SEED_DEMO_PET"] = "true"
os.environ["ROUTING_PROVIDER"] = "none"
# 개발자의 .env 설정과 무관하게 같은 결과가 나오도록 고정한다. 환경변수가 .env보다 우선한다.
os.environ["LLM_PROVIDER"] = "none"
os.environ["RECOMMENDER_WEIGHTS"] = "{}"
os.environ["SERVICE_AREA"] = "mangwon"
os.environ["AUTH_REQUIRED"] = "false"
# 내 산책길 코스 등록 때 실제 Overpass를 부르지 않는다. 측정은 테스트가 가짜 서버로 따로 확인한다.
os.environ["ENVIRONMENT_PROVIDER"] = "none"
# 가짜 Google 클라이언트. 토큰 교환은 테스트가 가짜 Google 서버로 바꿔 끼우므로 실제 Google을 부르지 않는다.
os.environ["GOOGLE_CLIENT_ID"] = "test-client.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-google-secret"
os.environ["GOOGLE_REDIRECT_URI"] = "http://testserver/api/auth/google/callback"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.recommender.types import (  # noqa: E402
    CourseData,
    HourWeather,
    PetProfile,
    PreferenceState,
    Schedule,
    TimeWindow,
)
from app.seed import seed_all  # noqa: E402

COURSES_PATH = Path(__file__).parent.parent / "app" / "data" / "courses.json"
NOW = datetime(2026, 10, 30, 10, 0)


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_all(db)
    with TestClient(app) as test_client:
        yield test_client


def make_pet(**overrides) -> PetProfile:
    values = dict(
        name="두부",
        age_years=5,
        weight_kg=4.2,
        size="small",
        activity_level="medium",
        personality="timid",
        path_preference="familiar",
        heat_sensitivity="medium",
        novelty_reaction="anxious",
    )
    values.update(overrides)
    return PetProfile(**values)


def make_course(id: int = 1, **overrides) -> CourseData:
    values = dict(
        id=id,
        name=f"코스{id}",
        distance_km=1.5,
        duration_min=25,
        has_park=True,
        lighting="good",
        is_paved=True,
        crowd_level="low",
        pet_allowed=True,
        is_familiar=True,
        shade_level=0.5,
        difficulty="easy",
        traffic_exposure="low",
        scenery_tags=("park",),
        facility_counts={},
    )
    values.update(overrides)
    return CourseData(**values)


def make_hour(time: datetime, **overrides) -> HourWeather:
    values = dict(
        time=time,
        temperature=18.0,
        apparent_temperature=18.0,
        precipitation_probability=10.0,
        precipitation_mm=0.0,
        humidity=55.0,
        wind_speed=2.0,
        uv_index=2.0,
        is_day=7 <= time.hour < 18,
    )
    values.update(overrides)
    return HourWeather(**values)


def make_forecast(now: datetime = NOW, hours: int = 48, rule=None) -> list[HourWeather]:
    """rule(time)이 돌려주는 값으로 특정 시간의 날씨를 덮어쓴 예보를 만든다."""
    first = now.replace(minute=0)
    rows = []
    for offset in range(hours):
        time = first + timedelta(hours=offset)
        rows.append(make_hour(time, **(rule(time) if rule else {})))
    return rows


def default_schedule(**overrides) -> Schedule:
    values = dict(windows=(TimeWindow(16, 20),), preferred_duration_min=40, walks_per_day=1)
    values.update(overrides)
    return Schedule(**values)


def seed_course_data() -> list[CourseData]:
    """실제 시드 코스를 엔진 입력 형태로 불러온다."""
    from collections import Counter

    courses = []
    for index, raw in enumerate(json.loads(COURSES_PATH.read_text(encoding="utf-8")), start=1):
        courses.append(
            CourseData(
                id=index,
                name=raw["name"],
                distance_km=raw["distance_km"],
                duration_min=raw["duration_min"],
                has_park=raw["has_park"],
                lighting=raw["lighting"],
                is_paved=raw["is_paved"],
                crowd_level=raw["crowd_level"],
                pet_allowed=raw["pet_allowed"],
                is_familiar=raw["is_familiar"],
                shade_level=raw["shade_level"],
                difficulty=raw["difficulty"],
                traffic_exposure=raw["traffic_exposure"],
                scenery_tags=tuple(raw["scenery_tags"]),
                facility_counts=dict(Counter(f["type"] for f in raw["facilities"])),
                environment=raw.get("environment") or {},
            )
        )
    return courses


EMPTY_STATE = PreferenceState()
