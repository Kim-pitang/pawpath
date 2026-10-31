"""추천 이력과 실제 행동으로 계산하는 온라인 평가 지표.

데이터 구분
- user: 로그인한 보호자의 기록. 실제 사용자 데이터다.
- demo: 로그인하지 않은 시연 보호자(id 1)의 기록. 팀의 시연과 시험이 섞여 있어 성능 근거로 쓰지 않는다.
- 시연용 걷기(tracking_source=simulation)는 어느 쪽 행동 지표에도 넣지 않는다.

표본이 MIN_SAMPLES보다 적으면 값은 보여 주되 reliable을 거짓으로 둔다. 값을 지어내지 않고, 계산할 수 없는
지표는 None과 이유를 돌려준다.
"""
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Pet, Recommendation, RecommendationEvent, RecommendationItem, WalkHistory
from app.recommender.config import V1
from app.recommender.evaluation import (
    RELEVANT_RATING,
    exposure_share,
    gini,
    graded_relevance,
    hit_rate_at_k,
    jaccard_distance,
    mean,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    repeat_rate,
)
from app.seed import DEFAULT_USER_ID
from app.services.report_service import is_simulated

MIN_SAMPLES = 30
RELEVANCE_WINDOW = timedelta(days=7)
NOT_MEASURED = {
    "save_rate": "추천 코스와 '나만의 산책길' 저장이 연결되어 있지 않아 측정하지 않아요.",
}


def _top(record: Recommendation) -> list[int]:
    return [course["course_id"] for course in sorted(record.payload.get("courses", []), key=lambda course: course["rank"])]


def _levels(record: Recommendation) -> list[str]:
    return [course.get("safety_assessment", {}).get("level", "") for course in record.payload.get("courses", [])]


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def compute_metrics(records: list[Recommendation], walks_by_pet: dict[int, list[WalkHistory]], events: dict[int, set[tuple[int, str]]], items: dict[int, list[RecommendationItem]]) -> dict:
    walkable = [record for record in records if record.walkable]
    n = len(walkable)
    # 버전을 남기기 전의 추천에는 선택과 출발 기록이 없다. 안 고른 것으로 세지 않도록 분모에서 뺀다.
    tracked = sum(1 for record in walkable if record.algorithm_version)

    selected = started = completed = 0
    satisfaction: list[float] = []
    revisits = linked_walks = 0
    ranking = defaultdict(list)
    new_course: list[float] = []
    missing: list[float] = []
    weather_age: list[float] = []
    danger_any = danger_top = 0
    passed = candidates = 0

    for record in walkable:
        top = _top(record)
        pet_walks = [walk for walk in walks_by_pet.get(record.pet_id, []) if not is_simulated(walk)]
        linked = [walk for walk in pet_walks if walk.recommendation_id == record.id]
        record_events = events.get(record.id, set())
        if record.algorithm_version and (linked or any(event == "select" for _, event in record_events)):
            selected += 1
        if record.algorithm_version and (linked or any(event == "start" for _, event in record_events)):
            started += 1
        if linked:
            completed += 1
        for walk in linked:
            linked_walks += 1
            if any(other.course_id == walk.course_id and other.started_at < walk.started_at for other in pet_walks):
                revisits += 1
            if walk.feedback:
                satisfaction.append(walk.feedback.pet_rating)

        # 이 추천으로 걸은 산책과 추천 뒤 7일 안에 만족도를 남긴 코스를 정답으로 본다. 평가하지 않은 코스는 정답도 오답도 아니다.
        # 다녀온 뒤에 기록하면 출발 시각이 추천보다 앞설 수 있어, 추천 번호로 이어진 산책은 시각과 관계없이 넣는다.
        window = [
            walk for walk in pet_walks
            if walk.feedback and (walk.recommendation_id == record.id or record.created_at <= walk.started_at < record.created_at + RELEVANCE_WINDOW)
        ]
        gains: dict[int, float] = {}
        for walk in window:
            gains[walk.course_id] = max(gains.get(walk.course_id, 0.0), graded_relevance(walk.feedback.pet_rating))
        if gains:
            relevant = {walk.course_id for walk in window if walk.feedback.pet_rating >= RELEVANT_RATING}
            ranking["precision"].append(precision_at_k(top, relevant))
            ranking["recall"].append(recall_at_k(top, relevant))
            ranking["hit"].append(hit_rate_at_k(top, relevant))
            ranking["ndcg"].append(ndcg_at_k(top, gains))

        walked_before = {walk.course_id for walk in pet_walks if walk.started_at < record.created_at}
        if top:
            new_course.append(sum(1 for course in top if course not in walked_before) / len(top))
        levels = _levels(record)
        danger_any += any(level == "danger" for level in levels)
        danger_top += bool(levels) and levels[0] == "danger"
        missing.extend(course.get("safety_assessment", {}).get("data_quality", {}).get("shares", {}).get("missing", 0.0) for course in record.payload.get("courses", []))
        if record.weather_fetched_at:
            weather_age.append((record.created_at - record.weather_fetched_at).total_seconds() / 60)
        record_items = items.get(record.id, [])
        candidates += len(record_items)
        passed += sum(1 for item in record_items if not item.excluded_reasons)

    by_pet = defaultdict(list)
    for record in sorted(walkable, key=lambda record: record.created_at):
        by_pet[record.pet_id].append(record)
    repeats = []
    for pet_records in by_pet.values():
        # 같은 날 다시 누른 추천은 같은 조건이라 빼고, 날짜가 바뀐 추천끼리 비교한다.
        daily = list({record.created_at.date(): record for record in pet_records}.values())
        repeats.extend(repeat_rate(_top(before), _top(after)) for before, after in zip(daily, daily[1:]))
    same_day = defaultdict(dict)
    for record in walkable:
        same_day[record.created_at.date()][record.pet_id] = _top(record)
    between_pets = [jaccard_distance(a, b) for tops in same_day.values() for i, a in enumerate(tops.values()) for b in list(tops.values())[i + 1 :]]

    changes = []
    for walks in walks_by_pet.values():
        ratings = [walk.feedback.pet_rating for walk in sorted(walks, key=lambda walk: walk.started_at) if walk.feedback and not is_simulated(walk)]
        if len(ratings) >= 4:
            half = len(ratings) // 2
            changes.append(sum(ratings[half:]) / len(ratings[half:]) - sum(ratings[:half]) / half)

    exposure = exposure_share(_top(record) for record in walkable)
    return {
        "recommendations": len(records),
        "walkable_recommendations": n,
        # 추천 자체로 계산하는 안전, 노출 지표의 표본. 순위와 행동 지표는 각자의 표본으로 따로 판단한다.
        "reliable": n >= MIN_SAMPLES,
        "ranking": {
            "samples": len(ranking["hit"]),
            "reliable": len(ranking["hit"]) >= MIN_SAMPLES,
            "precision_at_3": mean(ranking["precision"]),
            "recall_at_3": mean(ranking["recall"]),
            "ndcg_at_3": mean(ranking["ndcg"]),
            "hit_rate_at_3": mean(ranking["hit"]),
            "note": "추천 뒤 7일 안에 만족도를 남긴 코스만 정답 후보예요. 평가하지 않은 코스는 계산에서 모르는 값으로 둬요.",
        },
        "quality": {
            "reliable": tracked >= MIN_SAMPLES and len(satisfaction) >= MIN_SAMPLES,
            "tracked_recommendations": tracked,
            "selection_rate": _rate(selected, tracked),
            "start_rate": _rate(started, tracked),
            "completion_rate": _rate(completed, n),
            "average_pet_rating": mean(satisfaction),
            "rating_samples": len(satisfaction),
            "revisit_rate": _rate(revisits, linked_walks),
            "save_rate": None,
        },
        "safety": {
            "danger_in_top3_rate": _rate(danger_any, n),
            "danger_top1_rate": _rate(danger_top, n),
            "filter_pass_rate": _rate(passed, candidates),
            "candidate_samples": candidates,
            "missing_data_share": mean(missing),
            "weather_age_minutes": mean(weather_age),
        },
        "personalization": {
            "between_pet_difference": mean(between_pets),
            "between_pet_pairs": len(between_pets),
            "repeat_rate": mean(repeats),
            "new_course_rate": mean(new_course),
            "rating_change_after_feedback": mean(changes),
            "rating_change_pets": len(changes),
        },
        "exposure": {"top3_share": exposure, "gini": gini(list(exposure.values()))},
        "not_measured": NOT_MEASURED,
    }


def _load(db: Session, pet_ids: list[int]) -> tuple[list[Recommendation], dict, dict, dict]:
    if not pet_ids:
        return [], {}, {}, {}
    records = list(db.scalars(select(Recommendation).where(Recommendation.pet_id.in_(pet_ids)).order_by(Recommendation.created_at)))
    walks_by_pet: dict[int, list[WalkHistory]] = defaultdict(list)
    for walk in db.scalars(select(WalkHistory).where(WalkHistory.pet_id.in_(pet_ids))):
        walks_by_pet[walk.pet_id].append(walk)
    events: dict[int, set] = defaultdict(set)
    for event in db.scalars(select(RecommendationEvent).where(RecommendationEvent.pet_id.in_(pet_ids))):
        events[event.recommendation_id].add((event.course_id, event.event))
    items: dict[int, list] = defaultdict(list)
    for item in db.scalars(select(RecommendationItem).where(RecommendationItem.pet_id.in_(pet_ids))):
        items[item.recommendation_id].append(item)
    return records, walks_by_pet, events, items


def _by_version(records, walks_by_pet, events, items) -> dict:
    versions = defaultdict(list)
    for record in records:
        versions[record.algorithm_version or V1].append(record)
    return {
        "all": compute_metrics(records, walks_by_pet, events, items),
        "by_version": {version: compute_metrics(group, walks_by_pet, events, items) for version, group in sorted(versions.items())},
    }


def pet_metrics(db: Session, pet: Pet) -> dict:
    return {"pet_id": pet.id, "min_samples": MIN_SAMPLES, **_by_version(*_load(db, [pet.id]))}


def service_metrics(db: Session, now: datetime) -> dict:
    """운영자용 전체 통계. 개인 정보 없이 집계값만 돌려준다."""
    pets = list(db.scalars(select(Pet)))
    segments = {
        "user": [pet.id for pet in pets if pet.user_id != DEFAULT_USER_ID],
        "demo": [pet.id for pet in pets if pet.user_id == DEFAULT_USER_ID],
    }
    return {
        "generated_at": now.isoformat(),
        "min_samples": MIN_SAMPLES,
        "segments": {name: {"pets": len(ids), **_by_version(*_load(db, ids))} for name, ids in segments.items()},
        "notes": [
            "user는 로그인한 보호자의 실제 기록, demo는 시연 보호자의 기록이에요. demo는 성능 근거로 쓰지 않아요.",
            "시연용 걷기는 행동 지표에서 뺐어요.",
        ],
    }
