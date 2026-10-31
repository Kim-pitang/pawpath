"""추천 점수 설정과 순위 모델 인터페이스.

가중치는 RECOMMENDER_WEIGHTS 환경변수로 바꿀 수 있다. 순위 계산은 Ranker로 분리해 두어,
산책 데이터가 충분히 쌓이면 LightGBM Ranker 같은 학습 모델로 교체할 수 있다.
"""
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

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
    weights: Mapping[str, float] = field(default_factory=lambda: dict(BASE_WEIGHTS))
    user_preference_weight: float = USER_PREFERENCE_WEIGHT
    max_preference_gain: float = MAX_PREFERENCE_WEIGHT_GAIN
    ranker: Ranker = field(default_factory=WeightedSumRanker)


DEFAULT_CONFIG = ScoringConfig()


def parse_scoring_config(raw: str) -> ScoringConfig:
    """JSON 문자열로 가중치를 읽는다. 기본 항목의 합은 1이 되도록 맞춘다.

    예: {"weather": 0.3, "safety": 0.2, "user_preference": 0.15}
    """
    if not raw.strip():
        return DEFAULT_CONFIG
    values = json.loads(raw)
    if not isinstance(values, dict):
        raise ValueError("가중치는 JSON 객체여야 합니다")

    allowed = set(BASE_WEIGHTS) | {"user_preference"}
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"알 수 없는 가중치 항목: {sorted(unknown)}")
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError(f"가중치는 0 이상의 숫자여야 합니다: {key}")

    user_preference = float(values.get("user_preference", USER_PREFERENCE_WEIGHT))
    merged = {key: float(values.get(key, default)) for key, default in BASE_WEIGHTS.items()}
    total = sum(merged.values())
    if total <= 0:
        raise ValueError("기본 가중치의 합은 0보다 커야 합니다")
    return ScoringConfig(
        weights={key: value / total for key, value in merged.items()},
        user_preference_weight=user_preference,
    )
