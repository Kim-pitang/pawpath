import json

import httpx
import pytest

from app.database import SessionLocal
from app.models import Pet, Recommendation
from app.recommender.explain_guard import build_fact_sheet, rejection_reason
from app.services.llm_service import LlmUnavailable, OllamaProvider, build_provider, enhance_recommendation
from app.config import Settings

PET = {"이름": "두부", "특징": ["소심함", "활동량 보통", "익숙한 길을 좋아함"]}


class FakeProvider:
    name = "fake"
    model = "fake-1"

    def __init__(self, response=None, error=False):
        self.response = response
        self.error = error
        self.calls = []

    def complete(self, system, user, schema):
        self.calls.append((system, user, schema))
        if self.error:
            raise LlmUnavailable("ConnectError")
        return self.response(user) if callable(self.response) else self.response


def facts(**overrides):
    base = {
        "반려동물": PET,
        "코스": {"이름": "망원초록길 공원 코스", "거리_km": 1.6, "예상_시간_분": 25, "공원_포함": True, "공원_이름": ["망원정마당"], "확인된_시설": ["음수대 1곳"]},
        "추천_시간": "오후 4시",
        "체감온도": 21,
        "강수확률": 20,
        "비_오기_전_산책": True,
        "비_시작_시각": "17시",
        "위험요인": [],
        "확인_불가_항목": ["조명", "그늘"],
        "이_코스_피드백_횟수": 0,
        "기본_문장": "낯선 길을 싫어하는 두부를 위해 익숙한 공원 코스를 골랐어요.",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "text",
    [
        "두부가 좋아할 익숙한 공원 코스예요. 비가 오기 전 오후 4시에 약 25분 다녀오세요.",
        "오후 4시 체감 21도라 두부와 걷기 좋아요. 음수대도 기록되어 있어요.",
    ],
)
def test_grounded_sentences_pass(text):
    assert rejection_reason(text, facts()) is None


@pytest.mark.parametrize(
    "text,expected",
    [
        ("두부와 걷기 좋은 코스예요. 화장실도 가까이 있어요.", "근거 없는 내용"),
        ("두부와 벤치에서 쉬어 가기 좋은 코스예요.", "근거 없는 내용"),
        ("두부와 체감 30도에 걷기 좋은 코스예요.", "근거 없는 숫자"),
        ("이 코스는 95점으로 두부에게 가장 좋아요.", "근거 없는 숫자"),
        ("두부에게 완벽하게 안전합니다. 편하게 다녀오세요.", "단정 표현"),
        ("두부의 관절 치료에 도움이 되는 코스예요.", "단정 표현"),
        ("가로등이 많아 밤에도 두부와 걷기 좋아요.", "확인 불가 항목"),
        ("그늘이 많아 시원하게 두부와 걸을 수 있어요.", "확인 불가 항목"),
        ("익숙한 공원 코스예요. 비가 오기 전 다녀오세요.", "이름이 없음"),
        ("두부와 걷기 좋아요. 공원 내에 음수대가 있어요.", "위치 표현"),
        ("두부 좋아요", "길이"),
        ("두부" + "가 좋아할 코스예요." * 40, "길이"),
    ],
)
def test_unfounded_sentences_are_rejected(text, expected):
    assert expected in rejection_reason(text, facts())


def test_words_from_a_stated_risk_are_grounded_even_if_the_item_is_unverified():
    sheet = facts(**{"위험요인": ["더위에 노면이 뜨거울 수 있어요."], "확인_불가_항목": ["노면", "조명"]})
    assert rejection_reason("더운 날이라 노면이 뜨거울 수 있어요. 두부의 발을 살펴 주세요.", sheet) is None
    # 위험요인에 없는 다른 확인 불가 항목은 여전히 막는다.
    assert "확인 불가 항목" in rejection_reason("가로등이 있어 두부와 걷기 좋아요.", sheet)


def test_fact_sheet_has_no_scores_and_only_confirmed_facilities(client):
    pet_id = client.get("/api/pets").json()[0]["id"]
    course = client.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": "rain_later"}).json()["courses"][0]
    sheet = build_fact_sheet(PET, course)
    text = json.dumps(sheet, ensure_ascii=False)
    assert "total_score" not in text and "점수" not in text
    assert sheet["비_오기_전_산책"] is True
    assert sheet["비_시작_시각"] == "17시" or sheet["비_시작_시각"].endswith("시")
    assert sheet["확인_불가_항목"]


def _recommend(client, scenario="rain_later") -> int:
    pet_id = client.get("/api/pets").json()[0]["id"]
    return client.post("/api/recommendations", json={"pet_id": pet_id, "weather_scenario": scenario}).json()["id"]


def _enhance(record_id, provider):
    with SessionLocal() as db:
        record = db.get(Recommendation, record_id)
        pet = db.get(Pet, record.pet_id)
        return enhance_recommendation(db, record, pet, provider).payload


def _scores(payload):
    return [(course["course_id"], course["rank"], course["total_score"], course["factors"]) for course in payload["courses"]]


def _good_response(user):
    items = json.loads(user.split("\n", 1)[1])
    return json.dumps({"reasons": [{"course_id": item["course_id"], "text": f"{item['반려동물']['이름']}와 걷기 좋은 {item['추천_시간']} 산책 코스예요."} for item in items]})


def test_good_llm_text_is_stored_next_to_the_template_and_scores_do_not_change(client):
    record_id = _recommend(client)
    before = client.get(f"/api/recommendations/{record_id}").json()
    provider = FakeProvider(_good_response)
    after = _enhance(record_id, provider)

    assert after["explanation_engine"]["status"] == "ok"
    assert after["explanation_engine"]["accepted"] == 3
    assert _scores(after) == _scores(before)
    top = after["courses"][0]
    assert "두부" in top["reason"]["llm_summary"]
    # 템플릿 문장은 그대로 남는다.
    assert top["reason"]["summary"] == before["courses"][0]["reason"]["summary"]


def test_llm_receives_facts_but_no_scores(client):
    provider = FakeProvider(_good_response)
    _enhance(_recommend(client), provider)
    _, user, _ = provider.calls[0]
    assert "total_score" not in user
    assert "망원" in user


def test_llm_cannot_change_scores_even_if_it_tries(client):
    record_id = _recommend(client)
    before = client.get(f"/api/recommendations/{record_id}").json()

    def malicious(user):
        items = json.loads(user.split("\n", 1)[1])
        return json.dumps({"reasons": [{"course_id": item["course_id"], "text": "두부에게 100점짜리 코스예요."} for item in items], "total_score": 100, "rank": 1})

    after = _enhance(record_id, FakeProvider(malicious))
    assert _scores(after) == _scores(before)
    assert after["explanation_engine"]["status"] == "rejected"
    assert all("llm_summary" not in course["reason"] for course in after["courses"])


def test_fabricated_text_falls_back_to_the_template_per_course(client):
    record_id = _recommend(client)

    def mixed(user):
        items = json.loads(user.split("\n", 1)[1])
        reasons = [{"course_id": item["course_id"], "text": "두부와 놀이터에서 뛰어놀기 좋은 코스예요."} for item in items]
        reasons[0]["text"] = f"두부와 걷기 좋은 {items[0]['추천_시간']} 산책 코스예요."
        return json.dumps({"reasons": reasons})

    after = _enhance(record_id, FakeProvider(mixed))
    assert after["explanation_engine"]["status"] == "ok"
    assert after["explanation_engine"]["accepted"] == 1
    assert len(after["explanation_engine"]["rejected"]) == 2
    assert "llm_summary" in after["courses"][0]["reason"]
    assert "llm_summary" not in after["courses"][1]["reason"]


@pytest.mark.parametrize("provider", [FakeProvider(error=True), FakeProvider("이건 JSON이 아니에요"), FakeProvider('{"wrong": []}')])
def test_llm_failure_keeps_the_template(client, provider):
    record_id = _recommend(client)
    before = client.get(f"/api/recommendations/{record_id}").json()
    after = _enhance(record_id, provider)
    assert after["explanation_engine"]["status"] == "failed"
    assert _scores(after) == _scores(before)
    assert after["courses"][0]["reason"]["summary"] == before["courses"][0]["reason"]["summary"]


def test_successful_enhancement_is_not_repeated(client):
    record_id = _recommend(client)
    provider = FakeProvider(_good_response)
    _enhance(record_id, provider)
    _enhance(record_id, provider)
    assert len(provider.calls) == 1


def test_recommendation_with_no_course_skips_the_llm(client):
    record_id = _recommend(client, "heavy_rain")
    provider = FakeProvider(_good_response)
    assert _enhance(record_id, provider)["courses"] == []
    assert provider.calls == []


def test_without_llm_configuration_the_api_works_and_reports_template(client):
    record_id = _recommend(client)
    body = client.post(f"/api/recommendations/{record_id}/explain").json()
    assert body["explanation_engine"] == {"provider": "template", "model": None, "status": "disabled"}
    assert body["courses"][0]["reason"]["summary"]
    assert client.post("/api/recommendations/99999/explain").status_code == 404


def test_ollama_request_shape_and_response_parsing():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": '{"reasons": []}'}})

    provider = OllamaProvider("http://localhost:11434/", "test-model", 1.0, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert provider.complete("시스템", "사용자", {"type": "object"}) == '{"reasons": []}'
    assert seen["url"] == "http://localhost:11434/api/chat"
    assert seen["body"]["model"] == "test-model"
    assert seen["body"]["stream"] is False
    assert seen["body"]["format"] == {"type": "object"}
    assert seen["body"]["messages"][0] == {"role": "system", "content": "시스템"}


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(500),
        lambda request: httpx.Response(404, json={"error": "model not found"}),
        lambda request: httpx.Response(200, json={"unexpected": True}),
        lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused")),
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow")),
    ],
)
def test_ollama_failures_raise_llm_unavailable(handler):
    provider = OllamaProvider("http://localhost:11434", "m", 1.0, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(LlmUnavailable):
        provider.complete("s", "u", {})


def test_provider_is_off_by_default():
    assert build_provider(Settings(llm_provider="none")) is None
    assert isinstance(build_provider(Settings(llm_provider="ollama")), OllamaProvider)
