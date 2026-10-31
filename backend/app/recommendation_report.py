"""추천 평가 명령.

    uv run python -m app.recommendation_report online            # 실제 기록 집계 (DB, 개인 정보 없음)
    uv run python -m app.recommendation_report offline [--quick]  # v1과 v2 오프라인 비교 (DB 쓰지 않음)

offline은 두 부분이다.
1. 조건 그리드: 반려견 프로필 x 날씨 x 일정 조합에서 안전 역전, 중복 코스, 노출 편중, 일관성을 센다.
   정답이 필요 없는 구조 점검이라 실제 성능 수치가 아니다.
2. 합성 사용자: 코스 특성에 대한 숨은 취향을 무작위로 정한 가상 반려견이 20일 동안 추천을 받고 산책, 피드백을
   남긴다. 숨은 취향으로 매긴 정답과 비교해 Precision/Recall/NDCG/Hit@3를 낸다. 가상 사용자의 결과이며
   실제 사용자 성능이 아니다. 취향 모형이 엔진의 학습 특성과 같은 축을 써서 학습에 유리하다는 한계도 있다.
"""
import argparse
import itertools
import json
import math
import random
import sys
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from app.recommender.config import DEFAULT_CONFIG, GROUP_WEIGHTS, LEGACY_CONFIG, V1, ScoringConfig
from app.recommender.diversity import DUPLICATE_OVERLAP, route_overlap
from app.recommender.engine import recommend
from app.recommender.evaluation import exposure_share, gini, graded_relevance, hit_rate_at_k, mean, ndcg_at_k, precision_at_k, recall_at_k
from app.recommender.features import build_features
from app.recommender.preference import apply_feedback, course_vector, feedback_signal, record_visit
from app.recommender.types import CourseData, FeedbackInput, PetProfile, PreferenceState, Schedule, TimeWindow, WalkSample
from app.services.weather_providers import MockWeatherProvider, scenario_forecast

DATA_DIR = Path(__file__).parent / "data"
AREAS = {"mangwon": DATA_DIR / "courses.json", "gaepo": DATA_DIR / "courses_gaepo.json"}
NOW = datetime(2026, 10, 30, 10, 0)
WEATHERS = ("mild", "rain_later", "rain_now", "heatwave", "cold", "heavy_rain")
SCHEDULES = {"evening": Schedule((TimeWindow(16, 20),), 40, 1), "morning": Schedule((TimeWindow(7, 9),), 40, 1), "night": Schedule((TimeWindow(20, 23),), 40, 1)}
VERSIONS = {"rule-v1": LEGACY_CONFIG, "rule-v2": DEFAULT_CONFIG}
# 민감도 확인용: 피드백 조정 비중만 15%에서 30%로 올린 v2. 서비스 기본값이 아니다.
SENSITIVITY = {"rule-v2 (feedback 30%)": ScoringConfig(group_weights={**GROUP_WEIGHTS, "feedback": 0.30})}
LEVEL = {"good": 0, "caution": 0, "danger": 1}


def load_courses(path: Path) -> list[CourseData]:
    courses = []
    for index, raw in enumerate(json.loads(path.read_text(encoding="utf-8")), start=1):
        courses.append(
            CourseData(
                id=index, name=raw["name"], distance_km=raw["distance_km"], duration_min=raw["duration_min"], has_park=raw["has_park"],
                lighting=raw["lighting"], is_paved=raw["is_paved"], crowd_level=raw["crowd_level"], pet_allowed=raw["pet_allowed"],
                is_familiar=raw["is_familiar"], shade_level=raw["shade_level"], difficulty=raw["difficulty"], traffic_exposure=raw["traffic_exposure"],
                scenery_tags=tuple(raw["scenery_tags"]), facility_counts=dict(Counter(f["type"] for f in raw["facilities"])),
                environment=raw.get("environment") or {}, route=tuple((p[0], p[1]) for p in raw["route"]),
            )
        )
    return courses


def pet_grid(step: int = 1) -> list[PetProfile]:
    weights = {"small": 4.5, "medium": 14.0, "large": 28.0}
    pets = [
        PetProfile("콩이", age, weights[size], size, activity, personality, path, "medium", reaction)
        for size, age, activity, personality, path, reaction in itertools.product(
            weights, (0.5, 4, 12), ("low", "medium", "high"), ("active", "timid", "curious"), ("familiar", "new"), ("calm", "anxious")
        )
    ]
    return pets[::step]


def _forecast(name: str, schedule: Schedule):
    if name == "mild":
        return MockWeatherProvider().fetch(0, 0, NOW)
    start = next(NOW + timedelta(hours=i) for i in range(1, 25) if any(w.start_hour <= (NOW + timedelta(hours=i)).hour < w.end_hour for w in schedule.windows))
    return scenario_forecast(name, NOW, start)


def grid_report(courses: list[CourseData], config: ScoringConfig, step: int) -> dict:
    """정답 없이 셀 수 있는 구조 지표."""
    runs = walkable = inversion = unsafe_when_safe_exists = duplicates = 0
    weight_sums = set()
    tops: list[list[int]] = []
    top1 = Counter()
    for schedule in SCHEDULES.values():
        for weather in WEATHERS:
            forecast = _forecast(weather, schedule)
            for pet in pet_grid(step):
                runs += 1
                result = recommend(pet, courses, forecast, schedule, PreferenceState(), NOW, config)
                weight_sums.add(round(sum(result.weights.values()), 3))
                if not result.walkable:
                    continue
                walkable += 1
                ids = [item.course.id for item in result.courses]
                tops.append(ids)
                top1[ids[0]] += 1
                levels = [LEVEL[item.safety.level] for item in result.courses]
                if any(levels[i] > levels[j] for i in range(len(levels)) for j in range(i + 1, len(levels))):
                    inversion += 1
                # TOP 3에 위험 코스가 있는데, 같은 시간대에 위험하지 않은 다른 후보가 있었는가. v2만 후보 기록이 있다.
                if 1 in levels and any(c.safety_level in ("good", "caution") and c.rank is None for c in result.candidates):
                    unsafe_when_safe_exists += 1
                pairs = itertools.combinations(result.courses, 2)
                if any(route_overlap(a.course.route, b.course.route) >= DUPLICATE_OVERLAP for a, b in pairs):
                    duplicates += 1
    exposure = exposure_share(tops)
    return {
        "runs": runs,
        "walkable": walkable,
        "weight_sums": sorted(weight_sums),
        "safety_inversion_rate": round(inversion / walkable, 4) if walkable else None,
        # v1은 TOP 3 밖 후보의 안전 수준을 남기지 않아 셀 수 없다.
        "danger_with_safe_candidate_left_out": round(unsafe_when_safe_exists / walkable, 4) if walkable and config.version != V1 else None,
        "duplicate_route_in_top3_rate": round(duplicates / walkable, 4) if walkable else None,
        "top1_max_share": round(max(top1.values()) / walkable, 4) if walkable else None,
        "top3_exposure_gini": gini(list(exposure.values())),
        "distinct_top3_sets": len({tuple(sorted(ids)) for ids in tops}),
    }


def consistency(courses: list[CourseData], config: ScoringConfig) -> bool:
    forecast = MockWeatherProvider().fetch(0, 0, NOW)
    pets = pet_grid(9)
    first = [[(i.course.id, i.total_score) for i in recommend(p, courses, forecast, SCHEDULES["evening"], PreferenceState(), NOW, config).courses] for p in pets]
    second = [[(i.course.id, i.total_score) for i in recommend(p, courses, forecast, SCHEDULES["evening"], PreferenceState(), NOW, config).courses] for p in pets]
    return first == second


# ---- 합성 사용자 시뮬레이션 ----

def hidden_rating(course: CourseData, taste: dict[str, float], ideal_km: float) -> float:
    """가상 반려견의 기대 만족도(1~5). 코스 특성 취향과 권장 거리에서 벗어난 정도로 정한다."""
    vector = course_vector(course)
    attribute = sum(taste[key] * (value - 0.5) for key, value in vector.items())
    distance = math.exp(-(math.log(course.distance_km / ideal_km) ** 2) / (2 * 0.5**2))
    return max(1.0, min(5.0, 3.0 + 2.0 * attribute + 1.5 * (distance - 0.5)))


def simulate(courses: list[CourseData], config: ScoringConfig, users: int, days: int, seed: int) -> dict:
    rng = random.Random(seed)
    forecast = MockWeatherProvider().fetch(0, 0, NOW)
    schedule = SCHEDULES["evening"]
    pets = pet_grid(1)
    per_day = {metric: [[] for _ in range(days)] for metric in ("precision", "recall", "ndcg", "hit", "chosen_rating")}
    for user in range(users):
        pet = rng.choice(pets)
        keys = list(course_vector(courses[0]))
        taste = {key: rng.uniform(-1, 1) if rng.random() < 0.5 else 0.0 for key in keys}
        ideal = build_features(pet).ideal_distance_km
        truth = {course.id: hidden_rating(course, taste, ideal) for course in courses}
        relevant = {course_id for course_id, rating in truth.items() if rating >= 3.5}
        gains = {course_id: graded_relevance(rating) for course_id, rating in truth.items()}
        state = PreferenceState()
        walks: list[WalkSample] = []
        user_rng = random.Random(seed * 1000 + user)
        for day in range(days):
            now = NOW + timedelta(days=day)
            day_forecast = [replace(hour, time=hour.time + timedelta(days=day)) for hour in forecast]
            result = recommend(pet, courses, day_forecast, schedule, replace(state, walks=tuple(walks)), now, config)
            ranked = [item.course.id for item in result.courses]
            if not ranked:
                continue
            per_day["precision"][day].append(precision_at_k(ranked, relevant))
            per_day["recall"][day].append(recall_at_k(ranked, relevant))
            per_day["ndcg"][day].append(ndcg_at_k(ranked, gains))
            per_day["hit"][day].append(hit_rate_at_k(ranked, relevant))
            # 보호자는 70%는 TOP 3 중 마음에 드는 코스를, 30%는 1위를 고른다.
            if user_rng.random() < 0.7:
                chosen = max(ranked, key=lambda course_id: truth[course_id] + user_rng.gauss(0, 0.5))
            else:
                chosen = ranked[0]
            rating = int(max(1, min(5, round(truth[chosen] + user_rng.gauss(0, 0.5)))))
            per_day["chosen_rating"][day].append(rating)
            course = next(c for c in courses if c.id == chosen)
            feedback = FeedbackInput(rating, rating, "just_right", 4, rating >= 4)
            state = apply_feedback(record_visit(state, chosen), course, feedback, 16)
            walks.append(WalkSample(chosen, course.distance_km, course.duration_min, course.duration_min, 16, "manual", feedback_signal(feedback), "just_right"))
    def window(metric, start, end):
        return mean(value for day in per_day[metric][start:end] for value in day)
    return {
        metric: {"day_1_5": window(metric, 0, 5), "day_16_20": window(metric, days - 5, days)}
        for metric in per_day
    }


def offline(quick: bool) -> dict:
    step = 9 if quick else 1
    users = 30 if quick else 120
    report = {"label": "오프라인 실험: 조건 그리드와 합성 사용자. 실제 사용자 성능이 아님", "areas": {}}
    for area, path in AREAS.items():
        courses = load_courses(path)
        report["areas"][area] = {
            version: {
                "grid": grid_report(courses, config, step),
                "deterministic": consistency(courses, config),
                "synthetic_users": simulate(courses, config, users, 20, seed=7),
            }
            for version, config in VERSIONS.items()
        }
        for label, config in SENSITIVITY.items():
            report["areas"][area][label] = {"synthetic_users": simulate(courses, config, users, 20, seed=7)}
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("online", "offline"))
    parser.add_argument("--quick", action="store_true", help="offline을 작은 표본으로 빠르게 돌린다")
    args = parser.parse_args()
    if args.mode == "online":
        from app.clock import now_local
        from app.database import SessionLocal
        from app.services.recommendation_metrics import service_metrics

        with SessionLocal() as db:
            report = service_metrics(db, now_local())
    else:
        report = offline(args.quick)
    json.dump(report, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
