"""추천 점수 설정과 순위 모델 인터페이스.

가중치는 RECOMMENDER_WEIGHTS 환경변수로 바꿀 수 있다. 순위 계산은 Ranker로 분리해 두어,
산책 데이터가 충분히 쌓이면 LightGBM Ranker 같은 학습 모델로 교체할 수 있다.

알고리즘 버전
- rule-v1: 6항목 가중합 - 위험 감점. 가중치 합이 100%를 넘고(110~128%) 같은 산책이 여러 항목에 겹쳐 반영된다.
- rule-v2: 안전 단계를 먼저 적용한 뒤 5개 묶음 가중합. 데이터가 없는 묶음의 가중치는 나머지에 비례해 나눠
  합계를 늘 100%로 맞춘다. RECOMMENDER_VERSION=v1로 이전 동작으로 되돌릴 수 있다.
"""
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

V1 = "rule-v1"
V2 = "rule-v2"
VERSIONS = {"v1": V1, "v2": V2}

# v2 개인화 묶음의 초기 가중치. 고도화 지시서의 실험 기준값을 그대로 쓴다. 안전은 점수가 아니라 앞 단계의 필터다.
GROUP_WEIGHTS = {
    "pet_fit": 0.25,
    "user_preference": 0.25,
    "distance_time": 0.20,
    "weather_env": 0.15,
    "feedback": 0.15,
}
# 피드백 n건일 때 피드백 조정은 기준 가중치의 n / (n + FEEDBACK_RAMP)만 쓴다. 1건 50%, 3건 75%, 9건 90%.
FEEDBACK_RAMP = 1.0

BASE_WEIGHTS = {
    "weather": 0.25,
    "personality": 0.25,
    "activity": 0.15,
    "schedule": 0.15,
    "safety": 0.10,
    "preference": 0.10,
}
# 사용자 선호도는 입력이 없으면 중립값이라 점수에 영향을 주지 않으므로 합계 1에 포함하지 않는다.
USER_PREFERENCE_WEIGHT = 0.10
MAX_PREFERENCE_WEIGHT_GAIN = 0.20


class Ranker(Protocol):
    """코스 하나의 최종 점수를 계산한다."""

    name: str

    def score(self, contributions: Mapping[str, float], factor_scores: Mapping[str, float], penalty: float) -> float: ...


class WeightedSumRanker:
    """규칙 기반 기본 모델: 항목별 기여도의 합에서 위험 감점을 뺀다."""

    name = "weighted-sum"

    def score(self, contributions: Mapping[str, float], factor_scores: Mapping[str, float], penalty: float) -> float:
        return sum(contributions.values()) - penalty


@dataclass(frozen=True)
class ScoringConfig:
    # v1 가중치
    weights: Mapping[str, float] = field(default_factory=lambda: dict(BASE_WEIGHTS))
    user_preference_weight: float = USER_PREFERENCE_WEIGHT
    max_preference_gain: float = MAX_PREFERENCE_WEIGHT_GAIN
    ranker: Ranker = field(default_factory=WeightedSumRanker)
    version: str = V2
    # v2 가중치
    group_weights: Mapping[str, float] = field(default_factory=lambda: dict(GROUP_WEIGHTS))


DEFAULT_CONFIG = ScoringConfig()
LEGACY_CONFIG = ScoringConfig(version=V1)


def _normalized(values: Mapping, defaults: Mapping[str, float], label: str) -> dict[str, float]:
    merged = {key: float(values.get(key, default)) for key, default in defaults.items()}
    total = sum(merged.values())
    if total <= 0:
        raise ValueError(f"{label} 가중치의 합은 0보다 커야 합니다")
    return {key: value / total for key, value in merged.items()}


def parse_scoring_config(raw: str, version: str = V2) -> ScoringConfig:
    """JSON 문자열로 가중치를 읽는다. 버전마다 기본 항목의 합은 1이 되도록 맞춘다.

    v1 예: {"weather": 0.3, "safety": 0.2, "user_preference": 0.15}
    v2 예: {"pet_fit": 0.3, "feedback": 0.1}. 같은 이름인 user_preference는 v2 묶음 가중치로도 쓴다.
    """
    if not raw.strip():
        return DEFAULT_CONFIG if version == V2 else LEGACY_CONFIG
    values = json.loads(raw)
    if not isinstance(values, dict):
        raise ValueError("가중치는 JSON 객체여야 합니다")

    allowed = set(BASE_WEIGHTS) | {"user_preference"} | set(GROUP_WEIGHTS)
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"알 수 없는 가중치 항목: {sorted(unknown)}")
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"가중치는 0 이상의 숫자여야 합니다: {key}")

    user_preference = float(values.get("user_preference", USER_PREFERENCE_WEIGHT))
    return ScoringConfig(
        weights=_normalized(values, BASE_WEIGHTS, "v1"),
        user_preference_weight=user_preference,
        version=version,
        group_weights=_normalized(values, GROUP_WEIGHTS, "v2"),
    )
