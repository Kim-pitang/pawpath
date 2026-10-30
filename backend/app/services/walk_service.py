"""산책 기록과 피드백 처리. 피드백은 저장과 동시에 학습 상태를 갱신한다."""
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Pet, PetCoursePreference, Recommendation, WalkFeedback, WalkHistory, WalkingCourse
from app.recommender.preference import (
    NEUTRAL,
    TIME_BUCKETS,
    apply_feedback,
    attribute_insights,
    bucket_for_hour,
    feedback_signal,
    time_bucket_score,
)
from app.recommender.types import FeedbackInput
from app.services.recommendation_service import load_state, to_course_data


def _preference_row(db: Session, pet_id: int, course_id: int) -> PetCoursePreference:
    row = db.scalar(
        select(PetCoursePreference).where(
            PetCoursePreference.pet_id == pet_id,
            PetCoursePreference.course_id == course_id,
        )
    )
    if row is None:
        row = PetCoursePreference(
            pet_id=pet_id,
            course_id=course_id,
            affinity=NEUTRAL,
            weighted_sum=0.0,
            weight_total=0.0,
            visit_count=0,
            feedback_count=0,
        )
        db.add(row)
    return row


def record_walk(
    db: Session,
    pet: Pet,
    course: WalkingCourse,
    duration_min: int,
    started_at: datetime | None,
    recommendation_id: int | None,
    now: datetime,
) -> WalkHistory:
    started = started_at or now - timedelta(minutes=duration_min)
    walk = WalkHistory(
        pet_id=pet.id,
        course_id=course.id,
        recommendation_id=recommendation_id,
        started_at=started,
        ended_at=started + timedelta(minutes=duration_min),
        duration_min=duration_min,
        created_at=now,
    )
    db.add(walk)
    row = _preference_row(db, pet.id, course.id)
    row.visit_count += 1
    db.commit()
    return walk


def submit_feedback(db: Session, walk: WalkHistory, feedback: FeedbackInput, memo: str, now: datetime) -> WalkFeedback:
    pet = walk.pet
    course = walk.course
    state = load_state(db, pet)
    before = state.courses[course.id].affinity if course.id in state.courses else NEUTRAL

    updated = apply_feedback(state, to_course_data(course), feedback, walk.started_at.hour)
    course_state = updated.courses[course.id]

    row = _preference_row(db, pet.id, course.id)
    row.affinity = course_state.affinity
    row.weighted_sum = course_state.weighted_sum
    row.weight_total = course_state.weight_total
    row.feedback_count = course_state.feedback_count

    pet.learned_attribute_weights = updated.attribute_weights
    pet.learned_time_buckets = {key: asdict(value) for key, value in updated.time_buckets.items()}
    pet.feedback_total = updated.feedback_total

    record = WalkFeedback(
        walk_id=walk.id,
        pet_id=pet.id,
        course_id=course.id,
        walk_rating=feedback.walk_rating,
        pet_rating=feedback.pet_rating,
        difficulty=feedback.difficulty,
        weather_rating=feedback.weather_rating,
        would_revisit=feedback.would_revisit,
        memo=memo,
        signal=round(feedback_signal(feedback), 1),
        affinity_before=before,
        affinity_after=course_state.affinity,
        created_at=now,
    )
    db.add(record)
    db.commit()
    return record


def build_insights(db: Session, pet: Pet) -> dict:
    """마이페이지 분석: 통계, 자주 간 코스, 학습된 선호, 추천 결과 변화."""
    walks = list(
        db.scalars(select(WalkHistory).where(WalkHistory.pet_id == pet.id).order_by(WalkHistory.started_at))
    )
    feedbacks = list(
        db.scalars(select(WalkFeedback).where(WalkFeedback.pet_id == pet.id).order_by(WalkFeedback.id))
    )
    preferences = list(db.scalars(select(PetCoursePreference).where(PetCoursePreference.pet_id == pet.id)))
    state = load_state(db, pet)

    pet_ratings: dict[int, list[int]] = defaultdict(list)
    for feedback in feedbacks:
        pet_ratings[feedback.course_id].append(feedback.pet_rating)

    courses = [
        {
            "course_id": row.course_id,
            "course_name": row.course.name,
            "visit_count": row.visit_count,
            "feedback_count": row.feedback_count,
            "affinity": row.affinity,
            "average_pet_rating": round(sum(pet_ratings[row.course_id]) / len(pet_ratings[row.course_id]), 1)
            if pet_ratings[row.course_id]
            else None,
        }
        for row in preferences
    ]
    courses.sort(key=lambda item: (-item["visit_count"], -item["affinity"]))

    bucket_samples: dict[str, int] = defaultdict(int)
    for walk in walks:
        if walk.feedback is not None:
            bucket_samples[bucket_for_hour(walk.started_at.hour)] += 1

    recent = list(
        db.scalars(
            select(Recommendation)
            .where(Recommendation.pet_id == pet.id, Recommendation.walkable.is_(True))
            .order_by(Recommendation.id.desc())
            .limit(8)
        )
    )
    recent.reverse()

    return {
        "pet_id": pet.id,
        "pet_name": pet.name,
        "stats": {
            "walk_count": len(walks),
            "total_minutes": sum(walk.duration_min for walk in walks),
            "total_distance_km": round(sum(walk.course.distance_km for walk in walks), 2),
            "feedback_count": len(feedbacks),
            "average_pet_rating": round(sum(f.pet_rating for f in feedbacks) / len(feedbacks), 1) if feedbacks else None,
        },
        "courses": courses,
        "attributes": attribute_insights(state.attribute_weights),
        "attributes_learned": bool(state.attribute_weights),
        "time_preferences": [
            {
                "key": key,
                "label": label,
                "score": round(time_bucket_score(state, start), 1),
                "samples": bucket_samples[key],
            }
            for key, label, start, _ in TIME_BUCKETS
            if key != "night"
        ],
        "affinity_history": [
            {
                "feedback_id": feedback.id,
                "created_at": feedback.created_at,
                "course_id": feedback.course_id,
                "course_name": feedback.course.name,
                "pet_rating": feedback.pet_rating,
                "before": feedback.affinity_before,
                "after": feedback.affinity_after,
            }
            for feedback in feedbacks
        ],
        "recommendation_history": [
            {
                "id": record.id,
                "created_at": record.created_at,
                "scenario": record.weather_scenario,
                "feedback_total": record.payload["learning"]["feedback_total"],
                "courses": [
                    {
                        "rank": course["rank"],
                        "course_id": course["course_id"],
                        "name": course["name"],
                        "total_score": course["total_score"],
                    }
                    for course in record.payload["courses"]
                ],
            }
            for record in recent
        ],
    }
