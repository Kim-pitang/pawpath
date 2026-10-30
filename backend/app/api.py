"""REST API 라우터."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.clock import now_local
from app.database import get_db
from app.models import Pet, Recommendation, User, WalkFeedback, WalkHistory, WalkingCourse
from app.recommender.features import build_features
from app.recommender.timeslots import hour_comfort, is_rainy
from app.recommender.types import FeedbackInput
from app.seed import DEFAULT_USER_ID
from app.services.routing_service import Approach, plan_approach
from app.services.recommendation_service import create_recommendation, to_profile, windows_of
from app.services.walk_service import build_insights, record_walk, submit_feedback
from app.services.weather_service import WeatherResult, get_weather

router = APIRouter(prefix="/api")


def current_user(db: Session = Depends(get_db)) -> User:
    """MVP는 인증 없이 기본 보호자 1명으로 동작한다."""
    user = db.get(User, DEFAULT_USER_ID)
    if user is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "초기 데이터가 준비되지 않았습니다")
    return user


def _get_pet(db: Session, pet_id: int, user: User) -> Pet:
    pet = db.get(Pet, pet_id)
    if pet is None or pet.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "반려동물을 찾을 수 없습니다")
    return pet


@router.get("/health", tags=["시스템"])
def health() -> dict:
    return {"status": "ok", "service": "PawPath"}


# 반려동물
@router.post("/pets", response_model=schemas.PetRead, status_code=status.HTTP_201_CREATED, tags=["반려동물"])
def create_pet(body: schemas.PetCreate, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Pet:
    pet = Pet(user_id=user.id, **body.model_dump())
    db.add(pet)
    db.commit()
    return pet


@router.get("/pets", response_model=list[schemas.PetRead], tags=["반려동물"])
def list_pets(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[Pet]:
    return list(db.scalars(select(Pet).where(Pet.user_id == user.id).order_by(Pet.id)))


@router.get("/pets/{pet_id}", response_model=schemas.PetRead, tags=["반려동물"])
def get_pet(pet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Pet:
    return _get_pet(db, pet_id, user)


@router.put("/pets/{pet_id}", response_model=schemas.PetRead, tags=["반려동물"])
def update_pet(
    pet_id: int,
    body: schemas.PetUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Pet:
    pet = _get_pet(db, pet_id, user)
    for key, value in body.model_dump().items():
        setattr(pet, key, value)
    db.commit()
    return pet


@router.get("/pets/{pet_id}/insights", tags=["반려동물"])
def pet_insights(pet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    return build_insights(db, _get_pet(db, pet_id, user))


# 보호자 일정
def _merge_windows(windows: list[schemas.TimeWindowSchema]) -> list[dict]:
    """겹치거나 이어지는 시간대를 합친다. 산책이 시간대 경계를 넘어도 가능 시간 안으로 판단한다."""
    merged: list[dict] = []
    for window in sorted(windows, key=lambda w: w.start_hour):
        if merged and window.start_hour <= merged[-1]["end_hour"]:
            merged[-1]["end_hour"] = max(merged[-1]["end_hour"], window.end_hour)
        else:
            merged.append(window.model_dump())
    return merged


@router.get("/schedule", response_model=schemas.ScheduleSchema, tags=["보호자 일정"])
def get_schedule(user: User = Depends(current_user)) -> User:
    return user


@router.put("/schedule", response_model=schemas.ScheduleSchema, tags=["보호자 일정"])
def update_schedule(
    body: schemas.ScheduleSchema,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> User:
    user.available_windows = _merge_windows(body.available_windows)
    user.preferred_duration_min = body.preferred_duration_min
    user.walks_per_day = body.walks_per_day
    db.commit()
    return user


# 날씨
def _load_weather(db: Session, user: User, scenario: str) -> WeatherResult:
    return get_weather(db, now_local(), windows_of(user), scenario)


def _condition(rainy: bool, temperature: float) -> str:
    """하늘 상태 데이터는 받지 않으므로 강수와 기온으로 알 수 있는 내용만 말한다."""
    if rainy:
        return "비 소식 있음"
    if temperature >= 28:
        return "더움"
    if temperature >= 20:
        return "따뜻함"
    if temperature >= 10:
        return "선선함"
    if temperature >= 0:
        return "쌀쌀함"
    return "추움"


@router.get("/weather/current", response_model=schemas.CurrentWeather, tags=["날씨"])
def weather_current(
    scenario: schemas.WeatherScenario = "live",
    pet_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    result = _load_weather(db, user, scenario)
    current = result.hours[0]

    hint = "오늘의 산책각을 확인해 보세요."
    if pet_id is not None:
        pet = _get_pet(db, pet_id, user)
        comfort = hour_comfort(current, build_features(to_profile(pet)))
        hint = f"지금 {pet.name} 기준 날씨 적합도 {comfort:.0f}점"

    return {
        "source": result.source,
        "scenario": result.scenario,
        "is_mock": result.is_mock,
        "notice": result.notice,
        "current": current,
        "condition": _condition(is_rainy(current), current.temperature),
        "walk_comfort_hint": hint,
    }


@router.get("/weather/forecast", response_model=schemas.ForecastWeather, tags=["날씨"])
def weather_forecast(
    scenario: schemas.WeatherScenario = "live",
    hours: int = Query(default=24, ge=1, le=48),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    result = _load_weather(db, user, scenario)
    return {
        "source": result.source,
        "scenario": result.scenario,
        "is_mock": result.is_mock,
        "notice": result.notice,
        "hours": result.hours[:hours],
    }


# 산책 코스
@router.get("/courses", response_model=list[schemas.CourseDetail], tags=["산책 코스"])
def list_courses(db: Session = Depends(get_db)) -> list[WalkingCourse]:
    return list(db.scalars(select(WalkingCourse).order_by(WalkingCourse.id)))


@router.get("/courses/{course_id}", response_model=schemas.CourseDetail, tags=["산책 코스"])
def get_course(course_id: int, db: Session = Depends(get_db)) -> WalkingCourse:
    course = db.get(WalkingCourse, course_id)
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "코스를 찾을 수 없습니다")
    return course


@router.post("/courses/{course_id}/approach", response_model=schemas.ApproachRead, tags=["산책 코스"])
def course_approach(course_id: int, body: schemas.ApproachRequest, db: Session = Depends(get_db)) -> Approach:
    """현재 위치에서 코스 출발점까지의 도보 경로. 위치는 저장하지 않으며, 로그에 남지 않도록 본문으로 받는다."""
    course = db.get(WalkingCourse, course_id)
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "코스를 찾을 수 없습니다")
    return plan_approach((body.latitude, body.longitude), (course.start_lat, course.start_lng))


# 추천
def _recommendation_response(record: Recommendation) -> dict:
    return {"id": record.id, "created_at": record.created_at, **record.payload}


@router.post("/recommendations", status_code=status.HTTP_201_CREATED, tags=["추천"])
def post_recommendation(
    body: schemas.RecommendationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    pet = _get_pet(db, body.pet_id, user)
    return _recommendation_response(create_recommendation(db, pet, user, body.weather_scenario, now_local()))


@router.get("/recommendations", tags=["추천"])
def list_recommendations(
    pet_id: int,
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict]:
    _get_pet(db, pet_id, user)
    records = db.scalars(
        select(Recommendation).where(Recommendation.pet_id == pet_id).order_by(Recommendation.id.desc()).limit(limit)
    )
    return [_recommendation_response(record) for record in records]


@router.get("/recommendations/{recommendation_id}", tags=["추천"])
def get_recommendation(
    recommendation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    record = db.get(Recommendation, recommendation_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "추천 결과를 찾을 수 없습니다")
    _get_pet(db, record.pet_id, user)
    return _recommendation_response(record)


# 산책 기록
def _walk_response(walk: WalkHistory) -> dict:
    return {
        "id": walk.id,
        "pet_id": walk.pet_id,
        "course_id": walk.course_id,
        "course_name": walk.course.name,
        "distance_km": walk.course.distance_km,
        "recommendation_id": walk.recommendation_id,
        "started_at": walk.started_at,
        "ended_at": walk.ended_at,
        "duration_min": walk.duration_min,
        "feedback": walk.feedback,
    }


@router.post("/walks", response_model=schemas.WalkRead, status_code=status.HTTP_201_CREATED, tags=["산책 기록"])
def post_walk(body: schemas.WalkCreate, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    pet = _get_pet(db, body.pet_id, user)
    course = db.get(WalkingCourse, body.course_id)
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "코스를 찾을 수 없습니다")
    if body.recommendation_id is not None:
        recommendation = db.get(Recommendation, body.recommendation_id)
        if recommendation is None or recommendation.pet_id != pet.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "추천 결과를 찾을 수 없습니다")
    walk = record_walk(db, pet, course, body.duration_min, body.started_at, body.recommendation_id, now_local())
    return _walk_response(walk)


@router.get("/walks", response_model=list[schemas.WalkRead], tags=["산책 기록"])
def list_walks(
    pet_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict]:
    query = select(WalkHistory).join(Pet).where(Pet.user_id == user.id)
    if pet_id is not None:
        _get_pet(db, pet_id, user)
        query = query.where(WalkHistory.pet_id == pet_id)
    return [_walk_response(walk) for walk in db.scalars(query.order_by(WalkHistory.started_at.desc()))]


# 피드백
def _feedback_response(feedback: WalkFeedback) -> dict:
    return {
        "id": feedback.id,
        "walk_id": feedback.walk_id,
        "pet_id": feedback.pet_id,
        "course_id": feedback.course_id,
        "course_name": feedback.course.name,
        "walk_rating": feedback.walk_rating,
        "pet_rating": feedback.pet_rating,
        "difficulty": feedback.difficulty,
        "weather_rating": feedback.weather_rating,
        "would_revisit": feedback.would_revisit,
        "memo": feedback.memo,
        "signal": feedback.signal,
        "affinity_before": feedback.affinity_before,
        "affinity_after": feedback.affinity_after,
        "created_at": feedback.created_at,
    }


@router.post("/feedback", response_model=schemas.FeedbackRead, status_code=status.HTTP_201_CREATED, tags=["피드백"])
def post_feedback(body: schemas.FeedbackCreate, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    walk = db.get(WalkHistory, body.walk_id)
    if walk is None or walk.pet.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "산책 기록을 찾을 수 없습니다")
    if walk.feedback is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 피드백을 남긴 산책입니다")
    feedback = FeedbackInput(
        walk_rating=body.walk_rating,
        pet_rating=body.pet_rating,
        difficulty=body.difficulty,
        weather_rating=body.weather_rating,
        would_revisit=body.would_revisit,
    )
    return _feedback_response(submit_feedback(db, walk, feedback, body.memo, now_local()))


@router.get("/feedback/{pet_id}", response_model=list[schemas.FeedbackRead], tags=["피드백"])
def list_feedback(pet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict]:
    _get_pet(db, pet_id, user)
    records = db.scalars(select(WalkFeedback).where(WalkFeedback.pet_id == pet_id).order_by(WalkFeedback.id.desc()))
    return [_feedback_response(record) for record in records]
