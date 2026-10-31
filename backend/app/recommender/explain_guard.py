"""LLM 추천 이유의 근거 자료와 사실 검증.

LLM에는 추천 엔진이 계산한 사실만 전달하고, 돌아온 문장에 근거 없는 숫자나 시설, 단정적인
안전 표현이 있으면 버린다. 버린 경우 템플릿 문장을 그대로 쓴다.
"""
import json
import re

from app.recommender.text import hour_label

MAX_LENGTH = 200
MIN_LENGTH = 15

# 근거 자료에 있을 때만 말할 수 있는 낱말
GROUNDED_TERMS = (
    "그늘", "나무", "조명", "가로등", "화장실", "음수대", "동물병원", "경찰", "CCTV",
    "공원", "강변", "한강", "하천", "숲", "벤치", "잔디", "놀이터", "카페", "편의점",
)
# 근거가 있어도 말하면 안 되는 단정 표현
FORBIDDEN_CLAIMS = ("안전합니다", "안전해요", "안전한 코스", "보장", "치료", "건강에 좋", "문제없", "문제 없", "걱정 없", "걱정없", "무조건", "완벽")
# 시설은 경로 주변에 기록된 것일 뿐이라 공원 안에 있다고 말할 근거가 없다.
FORBIDDEN_LOCATIONS = ("공원 내", "공원 안", "코스 내", "코스 안", "바로 앞", "바로 옆")
# 데이터가 없어 확인할 수 없는 항목은 어떤 식으로도 단정하지 않게 한다.
UNVERIFIED_TERMS = {
    "조명": ("조명", "가로등", "밝은", "어두"),
    "그늘": ("그늘", "나무"),
    "차량 노출": ("차량", "차도", "도로"),
    "노면": ("포장", "흙길", "노면"),
    "주변 시설": ("화장실", "음수대", "동물병원"),
}


def build_fact_sheet(pet: dict, course: dict) -> dict:
    """저장된 추천 결과에서 LLM에 줄 사실만 고른다. 점수는 문장을 바꾸는 데 쓰이지 않도록 뺀다."""
    time = course["recommended_time"]
    weather = time["weather"]
    assessment = course.get("safety_assessment", {})
    safety = course.get("safety", {})
    facilities = [item["value"] for item in assessment.get("items", []) if item["key"] == "facilities" and item["status"] == "ok"]
    rain_onset = time.get("rain_onset")
    return {
        "반려동물": pet,
        "코스": {
            "이름": course["name"],
            "거리_km": round(course["distance_km"], 1),
            "예상_시간_분": course["duration_min"],
            "공원_포함": safety.get("has_park", False),
            "공원_이름": safety.get("park_names", []),
            "경로_주변에_기록된_시설": facilities,
        },
        "추천_시간": time["label"],
        "체감온도": round(weather["apparent_temperature"]),
        "강수확률": round(weather["precipitation_probability"]),
        "비_오기_전_산책": time.get("before_rain", False),
        "비_시작_시각": hour_label(int(rain_onset[11:13])) if rain_onset and time.get("before_rain") else None,
        "위험요인": assessment.get("risks", []),
        "확인_불가_항목": assessment.get("unverified", []),
        "이_코스_피드백_횟수": course.get("feedback_count", 0),
        "기본_문장": course["reason"]["summary"],
    }


def _allowed_numbers(text: str) -> set[str]:
    numbers = set(re.findall(r"\d+(?:\.\d+)?", text))
    return numbers | {str(round(float(number))) for number in numbers}


def rejection_reason(text: str, facts: dict) -> str | None:
    """문장을 쓸 수 없는 이유를 돌려준다. 문제가 없으면 None이다."""
    cleaned = text.strip()
    if not MIN_LENGTH <= len(cleaned) <= MAX_LENGTH:
        return "길이가 범위를 벗어남"

    name = facts["반려동물"]["이름"]
    if name not in cleaned:
        return "반려동물 이름이 없음"

    for claim in FORBIDDEN_CLAIMS:
        if claim in cleaned:
            return f"단정 표현 사용: {claim}"

    for phrase in FORBIDDEN_LOCATIONS:
        if phrase in cleaned:
            return f"근거 없는 위치 표현: {phrase}"

    # 위험요인 문구에 나온 낱말은 근거가 있으므로 허용한다. 예: 더위의 "노면이 뜨거울 수 있어요"
    risk_text = " ".join(facts.get("위험요인", []))
    for label in facts.get("확인_불가_항목", []):
        for term in UNVERIFIED_TERMS.get(label, (label,)):
            if term in cleaned and term not in risk_text:
                return f"확인 불가 항목 언급: {term}"

    grounded = {key: value for key, value in facts.items() if key != "확인_불가_항목"}
    allowed_text = json.dumps(grounded, ensure_ascii=False)
    for term in GROUNDED_TERMS:
        if term in cleaned and term not in allowed_text:
            return f"근거 없는 내용: {term}"

    allowed = _allowed_numbers(allowed_text)
    for number in re.findall(r"\d+(?:\.\d+)?", cleaned):
        if number not in allowed:
            return f"근거 없는 숫자: {number}"

    return None
