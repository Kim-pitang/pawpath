"""추천 이후 행동 기록과 추천 지표 API. 추천 계산은 api.py의 /recommendations에 있다."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import current_user
from app.clock import now_local
from app.database import get_db
from app.models import Pet, Recommendation, RecommendationEvent, RecommendationItem, User
from app.services.recommendation_metrics import pet_metrics

router = APIRouter(prefix="/api", tags=["추천"])


class EventCreate(BaseModel):
    course_id: int
    event: Literal["select", "start"]


def _own_recommendation(db: Session, recommendation_id: int, user: User) -> Recommendation:
    record = db.get(Recommendation, recommendation_id)
    pet = db.get(Pet, record.pet_id) if record else None
    if record is None or pet is None or pet.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "추천 결과를 찾을 수 없습니다")
    return record


@router.post("/recommendations/{recommendation_id}/events", status_code=status.HTTP_204_NO_CONTENT)
def post_event(recommendation_id: int, body: EventCreate, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
    """추천 카드에서 코스를 고르거나 길 안내에서 산책을 시작했을 때 남긴다. 같은 행동은 한 번만 센다."""
    record = _own_recommendation(db, recommendation_id, user)
    if body.course_id not in {course["course_id"] for course in record.payload.get("courses", [])}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "이 추천에 없는 코스입니다")
    exists = db.scalar(
        select(RecommendationEvent.id).where(
            RecommendationEvent.recommendation_id == record.id, RecommendationEvent.course_id == body.course_id, RecommendationEvent.event == body.event
        )
    )
    if exists:
        return
    db.add(RecommendationEvent(recommendation_id=record.id, pet_id=record.pet_id, course_id=body.course_id, event=body.event, created_at=now_local()))
    try:
        db.commit()
    except IntegrityError:
        # 화면이 같은 행동을 동시에 두 번 보냈다. 이미 남았으므로 그대로 둔다.
        db.rollback()


@router.get("/recommendations/{recommendation_id}/candidates")
def get_candidates(recommendation_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[dict]:
    """추천 당시 후보 코스 전부의 점수. TOP 3 밖과 제외된 코스도 나온다."""
    record = _own_recommendation(db, recommendation_id, user)
    items = db.scalars(select(RecommendationItem).where(RecommendationItem.recommendation_id == record.id).order_by(RecommendationItem.position))
    return [
        {
            "course_id": item.course_id,
            "algorithm_version": item.algorithm_version,
            "rank": item.rank,
            "position": item.position,
            "total_score": item.total_score,
            "personalization_score": item.personalization_score,
            "safety_penalty": item.safety_penalty,
            "skip_penalty": item.skip_penalty,
            "safety_level": item.safety_level,
            "safety_score": item.safety_score,
            "group_scores": item.group_scores,
            "data_quality": item.data_quality,
            "excluded_reasons": item.excluded_reasons,
            "duplicate_of": item.duplicate_of,
            "exploration": item.exploration,
        }
        for item in items
    ]


@router.get("/pets/{pet_id}/recommendation-metrics")
def get_pet_metrics(pet_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    """이 반려동물의 추천 지표. 표본이 적으면 reliable이 거짓이다."""
    pet = db.get(Pet, pet_id)
    if pet is None or pet.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "반려동물을 찾을 수 없습니다")
    return pet_metrics(db, pet)
