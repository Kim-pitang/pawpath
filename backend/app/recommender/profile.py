"""산책 기록과 피드백으로 만드는 선호 프로필 (v2).

행동마다 신뢰도를 다르게 둔다. 산책 뒤에 남긴 만족도가 가장 강한 근거이고, 피드백 없는 완료 기록은
약한 근거다. 시연용 산책은 쓰지 않는다. 추천을 누르지 않은 것은 여기서 쓰지 않는다(엔진의 skipped_days 참고).

표본이 적으면 값을 만들지 않는다. 만들지 않은 값은 추천 점수와 설명에 들어가지 않는다.
"""
import statistics
from dataclasses import dataclass

from app.recommender.types import WalkSample

SIMULATION = "simulation"
# 행동별 신뢰도. 피드백 = 1.0, 피드백 없이 끝낸 산책 = 0.3
RATED_WEIGHT = 1.0
COMPLETED_WEIGHT = 0.3
# 선호 거리를 만들 최소 근거. 피드백 2건이면 충분하고, 피드백 없는 기록만으로는 7건이 필요하다.
MIN_DISTANCE_EVIDENCE = 2.0
# 프로필로 계산한 권장 거리를 학습한 거리 쪽으로 옮기는 정도: 근거 / (근거 + 4). 피드백 2건이면 1/3, 8건이면 2/3.
DISTANCE_PRIOR = 4.0
# 힘들었다고 하면 그 거리를 0.8배로, 쉬웠다고 하면 1.2배로 보고 평균한다.
DIFFICULTY_SCALE = {"hard": 0.8, "just_right": 1.0, "easy": 1.2}
LOW_SIGNAL = 40.0
MIN_PACE_SAMPLES = 2
PACE_RANGE = (0.7, 1.5)


@dataclass(frozen=True)
class LearnedProfile:
    preferred_distance_km: float | None = None
    distance_evidence: float = 0.0
    rated_walks: int = 0
    completed_walks: int = 0
    # 실제 걸린 시간 / 코스 예상 시간. GPS로 기록한 산책에서만 계산한다.
    pace_ratio: float | None = None
    pace_samples: int = 0
    too_hard: int = 0
    too_easy: int = 0


def real_walks(samples: tuple[WalkSample, ...]) -> list[WalkSample]:
    return [sample for sample in samples if sample.tracking_source != SIMULATION]


def build_profile(samples: tuple[WalkSample, ...]) -> LearnedProfile:
    walks = real_walks(samples)
    weighted_sum = 0.0
    evidence = 0.0
    for walk in walks:
        weight = RATED_WEIGHT if walk.signal is not None else COMPLETED_WEIGHT
        # 만족하지 못한 산책은 거리 취향의 근거로 약하게만 쓴다. 다른 이유로 불만이었을 수 있다.
        if walk.signal is not None and walk.signal < LOW_SIGNAL:
            weight *= 0.5
        weighted_sum += weight * walk.distance_km * DIFFICULTY_SCALE.get(walk.difficulty or "just_right", 1.0)
        evidence += weight

    paces = [walk.actual_min / walk.expected_min for walk in walks if walk.tracking_source == "gps" and walk.expected_min > 0 and walk.actual_min > 0]
    pace = None
    if len(paces) >= MIN_PACE_SAMPLES:
        pace = round(max(PACE_RANGE[0], min(PACE_RANGE[1], statistics.median(paces))), 2)

    return LearnedProfile(
        preferred_distance_km=round(weighted_sum / evidence, 2) if evidence >= MIN_DISTANCE_EVIDENCE else None,
        distance_evidence=round(evidence, 2),
        rated_walks=sum(1 for walk in walks if walk.signal is not None),
        completed_walks=len(walks),
        pace_ratio=pace,
        pace_samples=len(paces),
        too_hard=sum(1 for walk in walks if walk.difficulty == "hard"),
        too_easy=sum(1 for walk in walks if walk.difficulty == "easy"),
    )


def adjusted_ideal_km(ideal_km: float, profile: LearnedProfile) -> tuple[float, float]:
    """(보정한 권장 거리, 학습 거리의 반영 비율). 학습한 거리가 없으면 프로필 값 그대로다.

    학습한 거리를 따로 점수 항목으로 켜면, 같은 산책 2건이 만족도와 거리 항목에 겹쳐 들어가 다른 코스가
    한꺼번에 5~12점 떨어졌다. 그래서 반려견 특성 점수의 권장 거리를 표본 수만큼만 옮긴다.
    """
    if profile.preferred_distance_km is None:
        return ideal_km, 0.0
    share = profile.distance_evidence / (profile.distance_evidence + DISTANCE_PRIOR)
    return round(ideal_km * (1 - share) + profile.preferred_distance_km * share, 2), round(share, 3)
