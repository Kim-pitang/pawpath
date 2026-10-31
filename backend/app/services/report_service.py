"""주간 산책 활동 리포트. 시연용 산책은 통계에서 빼고 건수만 따로 알려 준다."""
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Pet, Recommendation, WalkFeedback, WalkHistory

SIMULATION = "simulation"
TREND_LIMIT = 12
WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")


def walked_km(walk: WalkHistory) -> float:
    return walk.distance_km if walk.distance_km is not None else walk.course.distance_km


def is_simulated(walk: WalkHistory) -> bool:
    return walk.tracking_source == SIMULATION


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _summary(walks: list[WalkHistory]) -> dict:
    minutes = [walk.duration_min for walk in walks]
    ratings = [walk.feedback.pet_rating for walk in walks if walk.feedback]
    return {
        "walk_count": len(walks),
        "total_distance_km": round(sum(walked_km(walk) for walk in walks), 2),
        "total_minutes": sum(minutes),
        "average_minutes": _mean(minutes),
        "average_pet_rating": _mean(ratings),
    }


def _change(current: float, previous: float) -> dict:
    return {
        "difference": round(current - previous, 2),
        # 지난주 기록이 없으면 증감률을 계산하지 않는다.
        "percent": round((current - previous) / previous * 100) if previous else None,
    }


def _comparison(walk: WalkHistory, recommendation: Recommendation | None) -> dict | None:
    if recommendation is None:
        return None
    courses = recommendation.payload.get("courses", [])
    top = courses[0] if courses else None
    chosen = next((course for course in courses if course["course_id"] == walk.course_id), None)
    return {
        "walk_id": walk.id,
        "date": walk.started_at.date(),
        "recommended_top": top["name"] if top else None,
        "chosen": walk.course.name,
        "chosen_rank": chosen["rank"] if chosen else None,
        "followed_top": bool(top and top["course_id"] == walk.course_id),
    }


def build_report(db: Session, pet: Pet, now: datetime, week_offset: int = 0) -> dict:
    today: date = now.date()
    week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
    week_end = week_start + timedelta(days=6)
    previous_start = week_start - timedelta(weeks=1)

    all_walks = list(db.scalars(select(WalkHistory).where(WalkHistory.pet_id == pet.id).order_by(WalkHistory.started_at)))
    real = [walk for walk in all_walks if not is_simulated(walk)]
    in_range = lambda walk, start, end: start <= walk.started_at.date() <= end  # noqa: E731
    this_week = [walk for walk in real if in_range(walk, week_start, week_end)]
    previous_week = [walk for walk in real if in_range(walk, previous_start, week_start - timedelta(days=1))]
    simulated_this_week = sum(1 for walk in all_walks if is_simulated(walk) and in_range(walk, week_start, week_end))

    summary = _summary(this_week)
    previous = _summary(previous_week)

    by_day: dict[date, list[WalkHistory]] = defaultdict(list)
    for walk in this_week:
        by_day[walk.started_at.date()].append(walk)
    daily = []
    for offset in range(7):
        day = week_start + timedelta(days=offset)
        walks = by_day.get(day, [])
        daily.append(
            {
                "date": day,
                "weekday": WEEKDAYS[offset],
                "walk_count": len(walks),
                "distance_km": round(sum(walked_km(walk) for walk in walks), 2),
                "minutes": sum(walk.duration_min for walk in walks),
                "average_pet_rating": _mean([walk.feedback.pet_rating for walk in walks if walk.feedback]),
                "walks": [
                    {"id": walk.id, "course_name": walk.course.name, "distance_km": round(walked_km(walk), 2), "duration_min": walk.duration_min}
                    for walk in walks
                ],
            }
        )

    per_course: dict[int, dict] = {}
    for walk in real:
        entry = per_course.setdefault(walk.course_id, {"course_id": walk.course_id, "course_name": walk.course.name, "visit_count": 0, "ratings": []})
        entry["visit_count"] += 1
        if walk.feedback:
            entry["ratings"].append(walk.feedback.pet_rating)
    favorite_courses = sorted(
        (
            {
                "course_id": entry["course_id"],
                "course_name": entry["course_name"],
                "visit_count": entry["visit_count"],
                "average_pet_rating": _mean(entry["ratings"]),
            }
            for entry in per_course.values()
        ),
        key=lambda item: (-item["visit_count"], -(item["average_pet_rating"] or 0)),
    )[:5]

    real_ids = {walk.id for walk in real}
    feedbacks = list(db.scalars(select(WalkFeedback).where(WalkFeedback.pet_id == pet.id).order_by(WalkFeedback.id)))
    trend = [
        {
            "feedback_id": feedback.id,
            "date": feedback.walk.started_at.date(),
            "course_name": feedback.course.name,
            "pet_rating": feedback.pet_rating,
            "walk_rating": feedback.walk_rating,
        }
        for feedback in feedbacks
        if feedback.walk_id in real_ids
    ][-TREND_LIMIT:]

    comparisons = []
    for walk in this_week:
        if walk.recommendation_id is None:
            continue
        comparison = _comparison(walk, db.get(Recommendation, walk.recommendation_id))
        if comparison:
            comparisons.append(comparison)

    return {
        "pet_id": pet.id,
        "pet_name": pet.name,
        "week": {"start": week_start, "end": week_end, "offset": week_offset},
        "summary": summary,
        "previous_week": previous,
        "change": {
            "walk_count": _change(summary["walk_count"], previous["walk_count"]),
            "total_distance_km": _change(summary["total_distance_km"], previous["total_distance_km"]),
            "total_minutes": _change(summary["total_minutes"], previous["total_minutes"]),
        },
        "daily": daily,
        "favorite_courses": favorite_courses,
        "satisfaction_trend": trend,
        "recommendation_vs_actual": {
            "walks": comparisons,
            "followed_top_count": sum(1 for item in comparisons if item["followed_top"]),
            "in_top_three_count": sum(1 for item in comparisons if item["chosen_rank"] is not None),
        },
        "simulated_walks_excluded": simulated_this_week,
        "total_simulated_walks": sum(1 for walk in all_walks if is_simulated(walk)),
    }
