"""추천 평가 지표. DB와 무관한 순수 함수라 실제 기록 집계와 오프라인 실험이 같은 계산을 쓴다.

relevance는 0~1 등급이다. 만족도 점수(1~5)는 graded_relevance로 바꾼다. 4점 이상을 '맞는 추천'으로 본다.
"""
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence

K = 3
RELEVANT_RATING = 4


def graded_relevance(rating: int | float) -> float:
    """1점 0, 5점 1."""
    return max(0.0, min(1.0, (rating - 1) / 4))


def precision_at_k(ranked: Sequence[int], relevant: set[int], k: int = K) -> float:
    """상위 k개 중 맞는 코스의 비율. 후보가 k개보다 적어도 k로 나눈다."""
    return sum(1 for item in ranked[:k] if item in relevant) / k


def recall_at_k(ranked: Sequence[int], relevant: set[int], k: int = K) -> float | None:
    """맞는 코스 중 상위 k개에 들어간 비율. 맞는 코스가 없으면 정의되지 않는다."""
    if not relevant:
        return None
    return sum(1 for item in ranked[:k] if item in relevant) / len(relevant)


def hit_rate_at_k(ranked: Sequence[int], relevant: set[int], k: int = K) -> float:
    return 1.0 if any(item in relevant for item in ranked[:k]) else 0.0


def ndcg_at_k(ranked: Sequence[int], gains: Mapping[int, float], k: int = K) -> float | None:
    """등급 관련도(gains: 코스 → 0~1)로 계산한 NDCG. 관련도가 모두 0이면 정의되지 않는다."""
    ideal = sorted((gain for gain in gains.values() if gain > 0), reverse=True)[:k]
    if not ideal:
        return None
    dcg = sum(gains.get(item, 0.0) / math.log2(position + 2) for position, item in enumerate(ranked[:k]))
    idcg = sum(gain / math.log2(position + 2) for position, gain in enumerate(ideal))
    return dcg / idcg


def mean(values: Iterable[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return round(sum(present) / len(present), 4) if present else None


def jaccard_distance(a: Iterable[int], b: Iterable[int]) -> float:
    left, right = set(a), set(b)
    union = left | right
    return 1 - len(left & right) / len(union) if union else 0.0


def exposure_share(lists: Iterable[Sequence[int]]) -> dict[int, float]:
    """코스별로 TOP k에 나온 비율. 편중 점검에 쓴다."""
    lists = list(lists)
    counts = Counter(item for ranked in lists for item in ranked)
    return {item: round(count / len(lists), 4) for item, count in counts.most_common()} if lists else {}


def gini(values: Sequence[float]) -> float | None:
    """노출 불평등. 0이면 고르게, 1에 가까울수록 몇 코스에 몰린다."""
    values = sorted(values)
    if not values or sum(values) == 0:
        return None
    n = len(values)
    cumulative = sum((index + 1) * value for index, value in enumerate(values))
    return round((2 * cumulative) / (n * sum(values)) - (n + 1) / n, 4)


def repeat_rate(previous: Sequence[int], current: Sequence[int]) -> float | None:
    """이번 TOP k 중 바로 앞 추천에도 있던 코스의 비율."""
    if not current:
        return None
    return sum(1 for item in current if item in set(previous)) / len(current)
