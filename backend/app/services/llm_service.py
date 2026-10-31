"""추천 이유 문장 생성(선택 기능).

추천 순위와 점수가 확정된 뒤 문장만 다듬는다. 어떤 경우에도 점수를 바꾸지 않으며,
LLM을 끄거나 호출에 실패하면 템플릿 문장을 그대로 쓴다.
"""
import copy
import json
import logging
from typing import Protocol

import httpx
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import Pet, Recommendation
from app.recommender.explain_guard import build_fact_sheet, rejection_reason

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 반려동물 산책 추천 서비스의 문장을 다듬는 역할입니다.
추천 코스는 이미 정해졌습니다. 코스별 근거 자료를 보고 보호자에게 건넬 추천 이유를 작성하세요.

규칙:
- 근거 자료에 있는 사실만 씁니다. 자료에 없는 시설, 숫자, 날씨, 경험을 지어내지 않습니다.
- "확인_불가_항목"에 있는 항목(조명, 그늘 등)은 있다고도 없다고도 말하지 않습니다.
- 시설은 "코스 주변에 기록되어 있어요"라고만 씁니다. 공원 안이나 코스 안에 있다고 말하지 않습니다.
- "안전합니다"처럼 안전을 단정하거나 건강 효과를 말하지 않습니다.
- 순위나 점수를 언급하지 않습니다.
- 반려동물 이름을 넣어 친근한 존댓말로 1~2문장, 100자 안팎으로 씁니다.
- 위험요인이 있으면 조심할 점을 짧게 덧붙입니다.
- course_id는 자료의 값을 그대로 씁니다."""

REASON_SCHEMA = {
    "type": "object",
    "properties": {
        "reasons": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"course_id": {"type": "integer"}, "text": {"type": "string"}},
                "required": ["course_id", "text"],
            },
        }
    },
    "required": ["reasons"],
}


class LlmUnavailable(Exception):
    """LLM에서 응답을 받지 못했다."""


class LlmProvider(Protocol):
    name: str
    model: str

    def complete(self, system: str, user: str, schema: dict) -> str:
        """응답 본문 문자열을 돌려준다. 실패하면 LlmUnavailable을 던진다."""
        ...


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout_seconds: float, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.client = client

    def complete(self, system: str, user: str, schema: dict) -> str:
        try:
            client = self.client or httpx.Client(timeout=self.timeout_seconds)
            response = client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "think": False,
                    "format": schema,
                    "options": {"temperature": 0.3},
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                },
            )
            response.raise_for_status()
            return response.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise LlmUnavailable(type(exc).__name__) from None


def build_provider(settings: Settings | None = None) -> LlmProvider | None:
    settings = settings or get_settings()
    if settings.llm_provider == "ollama":
        return OllamaProvider(settings.llm_base_url, settings.llm_model, settings.llm_timeout_seconds)
    return None


def initial_engine_state(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    enabled = settings.llm_provider == "ollama"
    return {
        "provider": settings.llm_provider if enabled else "template",
        "model": settings.llm_model if enabled else None,
        "status": "pending" if enabled else "disabled",
    }


def _pet_facts(pet: Pet) -> dict:
    path = "익숙한 길을 좋아함" if pet.path_preference == "familiar" else "새로운 길을 좋아함"
    personality = {"active": "활발함", "timid": "소심함", "curious": "호기심 많음"}[pet.personality]
    activity = {"low": "활동량 낮음", "medium": "활동량 보통", "high": "활동량 높음"}[pet.activity_level]
    return {"이름": pet.name, "특징": [personality, activity, path]}


def enhance_recommendation(db: Session, record: Recommendation, pet: Pet, provider: LlmProvider | None = None) -> Recommendation:
    """추천 이유를 LLM 문장으로 보강해 저장한다. 점수와 순위는 건드리지 않는다."""
    provider = provider or build_provider()
    state = record.payload.get("explanation_engine", {})
    if provider is None or state.get("status") == "ok" or not record.payload.get("courses"):
        return record
    # 날씨 API 장애로 모의 날씨를 쓴 추천이다. 근거 자료의 기온이 사실이 아니므로 문장을 만들지 않는다.
    if record.payload.get("weather", {}).get("is_available") is False:
        return record

    payload = copy.deepcopy(record.payload)
    courses = payload["courses"]
    pet_facts = _pet_facts(pet)
    fact_sheets = {course["course_id"]: build_fact_sheet(pet_facts, course) for course in courses}
    request = json.dumps(
        [{"course_id": course_id, **facts} for course_id, facts in fact_sheets.items()],
        ensure_ascii=False,
    )

    accepted = 0
    rejected: list[str] = []
    try:
        raw = provider.complete(SYSTEM_PROMPT, f"코스별 근거 자료:\n{request}", REASON_SCHEMA)
        reasons = {item["course_id"]: item["text"] for item in json.loads(raw)["reasons"]}
    except LlmUnavailable as exc:
        logger.warning("LLM 호출 실패, 템플릿 문장을 유지합니다: %s", exc)
        payload["explanation_engine"] = {"provider": provider.name, "model": provider.model, "status": "failed"}
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning("LLM 응답 형식 오류, 템플릿 문장을 유지합니다")
        payload["explanation_engine"] = {"provider": provider.name, "model": provider.model, "status": "failed"}
    else:
        for course in courses:
            text = reasons.get(course["course_id"])
            problem = "응답 없음" if not isinstance(text, str) else rejection_reason(text, fact_sheets[course["course_id"]])
            if problem:
                rejected.append(f"{course['name']}: {problem}")
                continue
            course["reason"]["llm_summary"] = text.strip()
            accepted += 1
        if rejected:
            logger.info("LLM 문장 %d개를 사실 검증에서 제외했습니다: %s", len(rejected), rejected)
        payload["explanation_engine"] = {
            "provider": provider.name,
            "model": provider.model,
            "status": "ok" if accepted else "rejected",
            "accepted": accepted,
            "rejected": rejected,
        }

    record.payload = payload
    db.commit()
    return record
