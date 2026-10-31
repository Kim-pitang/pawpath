"""산책 안전 지수.

환경 항목별로 상태와 근거를 평가해 점수를 내고, 위험한 조건을 걸러 낸다.

원칙
- 데이터가 없는 항목은 안전하다고 보지 않는다. '확인 불가'로 표시하고 보수적인 점수를 준다.
- 값의 출처를 구분한다: 예보, 지도 기록(OSM), 팀 추정, 시연용, 확인 불가.
- 이 점수는 환경 위험을 비교하기 위한 참고값이며 의학적, 절대적 안전을 보장하지 않는다.
"""
from app.recommender.text import hour_label
from app.recommender.types import CourseData, HourWeather, PetFeatures, SafetyAssessment, SafetyItem, SlotEvaluation

FORECAST = "forecast"
DEMO = "demo"
OBSERVED = "observed"
ESTIMATED = "estimated"
UNKNOWN = "unknown"

SOURCE_LABELS = {
    FORECAST: "Open-Meteo 예보",
    DEMO: "모의·시연용 날씨",
    OBSERVED: "OpenStreetMap 기록",
    ESTIMATED: "팀 추정",
    UNKNOWN: "데이터 없음",
}

OK = "ok"
CAUTION = "caution"
DANGER = "danger"
UNVERIFIED = "unverified"

UNKNOWN_SCORE = 40.0
KNOWN_COVERAGE = 0.5
CAUTION_PENALTY = 1.5
DANGER_PENALTY = 5.0
MAX_PENALTY = 15.0
HOT_EXTREME_MARGIN = 6.0
LONG_WALK_MIN = 30
STRONG_WIND_MS = 10.0
GOOD_LEVEL = 75.0
DANGER_LEVEL = 50.0

DISCLAIMER = "안전 점수는 환경 위험을 비교하는 참고값이에요. 의학적, 절대적 안전을 보장하지 않아요."

LIGHTING_ESTIMATE_SCORE = {"good": 70.0, "partial": 55.0, "poor": 20.0}
LIGHTING_ESTIMATE_TEXT = {"good": "조명 양호", "partial": "일부 구간 조명", "poor": "조명 부족"}
TRAFFIC_ESTIMATE_SCORE = {"low": 70.0, "medium": 50.0, "high": 20.0}
TRAFFIC_ESTIMATE_TEXT = {"low": "차량 노출 적음", "medium": "차량 노출 보통", "high": "차량 노출 많음"}
FACILITY_TEXT = {"toilets": "화장실", "veterinary": "동물병원", "drinking_water": "음수대", "police": "경찰시설", "surveillance": "CCTV"}
SAFETY_FACILITIES = ("toilets", "police", "surveillance", "veterinary", "drinking_water")

WEIGHTS_DAY = {"temperature": 0.2, "rain": 0.2, "wind": 0.05, "uv": 0.05, "time": 0.05, "lighting": 0.05, "shade": 0.05, "traffic": 0.2, "surface": 0.1, "facilities": 0.1, "park": 0.05}
WEIGHTS_DARK = {"temperature": 0.15, "rain": 0.15, "wind": 0.05, "uv": 0.0, "time": 0.05, "lighting": 0.3, "shade": 0.0, "traffic": 0.15, "surface": 0.05, "facilities": 0.05, "park": 0.05}
WEIGHTS_WEATHER_ONLY = {"temperature": 0.45, "rain": 0.35, "wind": 0.1, "uv": 0.05, "time": 0.05}


def _clip(value: float) -> float:
    return max(0.0, min(100.0, value))


def _item(key: str, label: str, status: str, score: float | None, value: str, source: str, detail: str | None = None) -> SafetyItem:
    return SafetyItem(
        key=key,
        label=label,
        status=status,
        score=None if score is None else round(_clip(score), 1),
        value=value,
        source=source,
        source_label=SOURCE_LABELS[source],
        detail=detail,
    )


def temperature_item(hour: HourWeather, features: PetFeatures, source: str) -> SafetyItem:
    apparent = hour.apparent_temperature
    value = f"체감 {apparent:.0f}°C"
    if apparent > features.comfort_high:
        score = 100 - (apparent - features.comfort_high) * 100 / (features.unsafe_heat - features.comfort_high)
        status = DANGER if apparent >= features.comfort_high + HOT_EXTREME_MARGIN else CAUTION
        return _item("temperature", "더위", status, score, value, source, "더위에 노면이 뜨거울 수 있어요. 물을 챙기고 무리하지 마세요.")
    if apparent < features.comfort_low:
        score = 100 - (features.comfort_low - apparent) * 100 / (features.comfort_low - features.unsafe_cold)
        status = DANGER if apparent <= features.comfort_low - 8 else CAUTION
        return _item("temperature", "추위", status, score, value, source, "추운 시간이에요. 산책 시간을 줄이고 체온을 살펴 주세요.")
    return _item("temperature", "기온", OK, 100, value, source)


def rain_item(hour: HourWeather, source: str, overlap_min: int = 0, duration_min: int = 0, before_rain: bool = False, onset_hour: int | None = None) -> SafetyItem:
    probability = hour.precipitation_probability
    amount = hour.precipitation_mm
    share = overlap_min / duration_min if duration_min else 0.0
    score = 100 - max(0.0, probability - 30) * 0.7 - min(60.0, amount * 40) - share * 30
    value = f"강수 확률 {probability:.0f}%, {amount:.1f}mm"
    if amount >= 3:
        return _item("rain", "강수", DANGER, score, value, source, "강한 비 예보가 있어요.")
    if overlap_min > 0:
        return _item("rain", "강수", CAUTION, score, value, source, f"산책 중 {overlap_min}분이 비 예보와 겹쳐요.")
    if before_rain and onset_hour is not None:
        return _item("rain", "강수", CAUTION, score, value, source, f"{hour_label(onset_hour)}부터 비 예보가 있어요. 늦어지면 일찍 돌아오세요.")
    if probability >= 50:
        return _item("rain", "강수", CAUTION, score, value, source, "비가 올 가능성이 있어요.")
    return _item("rain", "강수", OK, score, value, source)


def wind_item(hour: HourWeather, source: str) -> SafetyItem:
    speed = hour.wind_speed
    score = 100.0 if speed <= 5 else 100 - (speed - 5) * 70 / 9
    value = f"초속 {speed:.1f}m"
    if speed >= STRONG_WIND_MS:
        return _item("wind", "바람", DANGER, score, value, source, "바람이 강해요. 개방된 길은 피하는 편이 좋아요.")
    if speed >= 6:
        return _item("wind", "바람", CAUTION, score, value, source, "바람이 다소 강해요.")
    return _item("wind", "바람", OK, score, value, source)


def uv_item(hour: HourWeather, source: str) -> SafetyItem:
    if hour.uv_index is None:
        return _item("uv", "자외선", UNVERIFIED, None, "확인 불가", UNKNOWN, "자외선 정보를 받지 못했어요.")
    if not hour.is_day:
        return _item("uv", "자외선", OK, 100, "해가 진 시간", source)
    index = hour.uv_index
    score = 100.0 if index <= 5 else 100 - (index - 5) * 10
    value = f"지수 {index:.0f}"
    if index >= 9:
        return _item("uv", "자외선", DANGER, score, value, source, "자외선이 매우 강해요.")
    if index >= 6:
        return _item("uv", "자외선", CAUTION, score, value, source, "자외선이 강해요.")
    return _item("uv", "자외선", OK, score, value, source)


def time_item(is_dark: bool, features: PetFeatures, source: str) -> SafetyItem:
    if not is_dark:
        return _item("time", "시간대", OK, 100, "해가 떠 있는 시간", source)
    sensitive = features.life_stage == "senior" or features.crowd_tolerance < 0.3
    status = CAUTION if sensitive else OK
    return _item("time", "시간대", status, 60, "해가 진 뒤", source, "어두운 시간이에요. 반사 용품을 챙겨 주세요." if sensitive else None)


def _share(environment: dict, section: str) -> dict | None:
    data = environment.get(section)
    return data if isinstance(data, dict) else None


def lighting_item(course: CourseData, is_dark: bool) -> SafetyItem:
    lit = _share(course.environment, "lit")
    if lit:
        known = lit.get("yes", 0.0) + lit.get("no", 0.0)
        if known >= KNOWN_COVERAGE:
            lit_share = lit.get("yes", 0.0) / known
            score = 100 * lit_share
            status = OK if lit_share >= 0.7 or not is_dark else (CAUTION if lit_share >= 0.3 else DANGER)
            return _item("lighting", "조명", status, score, f"기록된 구간의 {lit_share:.0%} 조명 있음", OBSERVED)

    if course.lighting in LIGHTING_ESTIMATE_SCORE:
        text = LIGHTING_ESTIMATE_TEXT[course.lighting]
        score = LIGHTING_ESTIMATE_SCORE[course.lighting]
        detail = "조명 기록이 부족해 확인할 수 없어요. 현장을 확인해 주세요."
        if is_dark and course.lighting == "poor":
            return _item("lighting", "조명", DANGER, score, f"확인 불가 (추정: {text})", ESTIMATED, "해가 진 뒤 어두울 수 있어요.")
        if is_dark and course.lighting == "partial":
            return _item("lighting", "조명", CAUTION, score, f"확인 불가 (추정: {text})", ESTIMATED, "해가 진 뒤 일부 구간이 어두울 수 있어요.")
        return _item("lighting", "조명", UNVERIFIED, score, f"확인 불가 (추정: {text})", ESTIMATED, detail)

    status = CAUTION if is_dark else UNVERIFIED
    return _item("lighting", "조명", status, UNKNOWN_SCORE, "확인 불가", UNKNOWN, "조명 정보가 없어요. 해가 진 뒤라면 조명을 챙겨 주세요.")


def shade_item(course: CourseData, hour: HourWeather, features: PetFeatures, is_dark: bool) -> SafetyItem:
    # 쾌적 범위를 넘어야 더운 것으로 본다.
    hot = hour.apparent_temperature > features.comfort_high
    trees = course.environment.get("trees")
    # 기록이 없다고 나무가 없는 것은 아니므로, 0%는 근거로 쓰지 않는다.
    if isinstance(trees, (int, float)) and trees > 0:
        score = _clip(30 + trees * 100)
        status = CAUTION if hot and trees < 0.3 and not is_dark else OK
        return _item("shade", "그늘", status, score, f"나무 기록 근접 구간 {trees:.0%}", OBSERVED, "나무 기록으로 짐작한 값이며 실제 그늘은 시간대에 따라 달라요." if status == CAUTION else None)

    level = course.shade_level
    score = 40 + level * 40
    text = "많음" if level >= 0.6 else ("적음" if level <= 0.3 else "보통")
    if hot and level <= 0.3 and not is_dark:
        return _item("shade", "그늘", CAUTION, score, f"확인 불가 (추정: {text})", ESTIMATED, "더운 시간에 그늘이 부족할 수 있어요.")
    return _item("shade", "그늘", UNVERIFIED, score, f"확인 불가 (추정: {text})", ESTIMATED, "그늘 기록이 없어 확인할 수 없어요.")


def traffic_item(course: CourseData, is_dark: bool) -> SafetyItem:
    road = _share(course.environment, "road")
    if road and road.get("unknown", 1.0) <= 0.3:
        pedestrian = road.get("pedestrian", 0.0)
        local = road.get("local", 0.0)
        major = road.get("major", 0.0)
        score = 100 * pedestrian + 80 * local + 20 * major + UNKNOWN_SCORE * road.get("unknown", 0.0)
        value = f"보행 전용 {pedestrian:.0%}, 생활도로 {local:.0%}, 큰 도로 {major:.0%}"
        if major >= 0.6 and is_dark:
            return _item("traffic", "차량 노출", DANGER, score, value, OBSERVED, "해가 진 뒤 큰 도로를 따라 걷는 구간이 많아요.")
        if major >= 0.3:
            return _item("traffic", "차량 노출", CAUTION, score, value, OBSERVED, "큰 도로를 따라 걷는 구간이 있어요.")
        return _item("traffic", "차량 노출", OK, score, value, OBSERVED)

    estimate = TRAFFIC_ESTIMATE_TEXT[course.traffic_exposure]
    score = TRAFFIC_ESTIMATE_SCORE[course.traffic_exposure]
    status = CAUTION if course.traffic_exposure == "high" else UNVERIFIED
    return _item("traffic", "차량 노출", status, score, f"확인 불가 (추정: {estimate})", ESTIMATED, "도로 기록이 부족해 확인할 수 없어요.")


def surface_item(course: CourseData, wet: bool) -> SafetyItem:
    surface = _share(course.environment, "surface")
    if surface:
        known = surface.get("paved", 0.0) + surface.get("unpaved", 0.0)
        if known >= KNOWN_COVERAGE:
            unpaved = surface.get("unpaved", 0.0) / known
            status = CAUTION if unpaved >= 0.3 and wet else OK
            return _item("surface", "노면", status, 100 - unpaved * 50, f"기록된 구간의 {1 - unpaved:.0%} 포장", OBSERVED, "젖으면 미끄러울 수 있어요." if status == CAUTION else None)

    if course.is_paved:
        return _item("surface", "노면", UNVERIFIED, 70, "확인 불가 (추정: 포장)", ESTIMATED, "노면 기록이 부족해 확인할 수 없어요.")
    status = CAUTION if wet else UNVERIFIED
    return _item("surface", "노면", status, 40, "확인 불가 (추정: 비포장)", ESTIMATED, "비포장 구간이 젖으면 미끄러울 수 있어요." if wet else "노면 기록이 부족해 확인할 수 없어요.")


def facilities_item(course: CourseData) -> SafetyItem:
    found = [(kind, course.facility_counts.get(kind, 0)) for kind in SAFETY_FACILITIES if course.facility_counts.get(kind, 0)]
    count = sum(number for _, number in found)
    if count == 0:
        return _item("facilities", "주변 시설", UNVERIFIED, UNKNOWN_SCORE, "기록된 시설 없음", UNKNOWN, "기록이 없을 뿐 실제로 없다는 뜻은 아니에요.")
    text = ", ".join(f"{FACILITY_TEXT[kind]} {number}곳" for kind, number in found)
    return _item("facilities", "주변 시설", OK, 40 + count * 20, text, OBSERVED)


def park_item(course: CourseData) -> SafetyItem:
    if course.has_park:
        return _item("park", "공원", OK, 100, "공원 포함", OBSERVED if course.environment else ESTIMATED)
    return _item("park", "공원", OK, 60, "공원 없음", OBSERVED if course.environment else ESTIMATED)


def _weighted_score(items: tuple[SafetyItem, ...], weights: dict[str, float]) -> float:
    total = 0.0
    weight_sum = 0.0
    for item in items:
        weight = weights.get(item.key, 0.0)
        total += weight * (UNKNOWN_SCORE if item.score is None else item.score)
        weight_sum += weight
    return total / weight_sum if weight_sum else 0.0


def _summarize(items: tuple[SafetyItem, ...], score: float, blocked: tuple[str, ...]) -> SafetyAssessment:
    dangers = [item for item in items if item.status == DANGER]
    cautions = [item for item in items if item.status == CAUTION]
    penalty = min(MAX_PENALTY, len(dangers) * DANGER_PENALTY + len(cautions) * CAUTION_PENALTY)

    if blocked:
        level = "blocked"
    elif dangers or score < DANGER_LEVEL:
        level = "danger"
    elif cautions or score < GOOD_LEVEL:
        level = "caution"
    else:
        level = "good"

    return SafetyAssessment(
        score=round(score, 1),
        level=level,
        items=items,
        risks=tuple(item.detail for item in [*dangers, *cautions] if item.detail),
        blocked_reasons=blocked,
        unverified=tuple(item.label for item in items if item.status == UNVERIFIED),
        penalty=penalty,
        disclaimer=DISCLAIMER,
    )


def _blocking_reasons(course: CourseData, slot: SlotEvaluation, features: PetFeatures, shade: SafetyItem, lighting: SafetyItem) -> tuple[str, ...]:
    """이 코스를 이 시간에 추천하지 않을 이유. 다른 시간이나 코스로 대체한다."""
    weather = slot.weather
    reasons: list[str] = []

    if slot.rain_overlap_min > 0 and not course.is_paved:
        reasons.append("비가 오는 시간에 비포장 구간이 미끄러울 수 있어요")

    very_hot = weather.apparent_temperature >= features.comfort_high + HOT_EXTREME_MARGIN
    shade_confirmed = shade.status == OK or course.shade_level >= 0.6
    if very_hot and slot.duration_min > LONG_WALK_MIN and not shade_confirmed:
        reasons.append(f"체감 {weather.apparent_temperature:.0f}°C에 {slot.duration_min}분을 걷기에는 그늘을 확인할 수 없어요")

    sensitive = features.life_stage == "senior" or features.crowd_tolerance < 0.3
    if slot.is_dark and sensitive and lighting.status == DANGER:
        reasons.append("해가 진 뒤 어두울 수 있어 겁이 많거나 나이 든 아이에게 맞지 않아요")

    if weather.wind_speed >= STRONG_WIND_MS and "river" in course.scenery_tags:
        reasons.append(f"초속 {weather.wind_speed:.0f}m 바람을 그대로 맞는 강변이에요")

    return tuple(reasons)


def assess_course(course: CourseData, slot: SlotEvaluation, features: PetFeatures, weather_source: str = FORECAST) -> SafetyAssessment:
    """특정 시간에 특정 코스를 걸을 때의 안전 지수."""
    weather = slot.weather
    wet = slot.rain_overlap_min > 0 or weather.precipitation_probability >= 50
    onset_hour = slot.rain_onset.hour if slot.rain_onset else None
    lighting = lighting_item(course, slot.is_dark)
    shade = shade_item(course, weather, features, slot.is_dark)
    items = (
        temperature_item(weather, features, weather_source),
        rain_item(weather, weather_source, slot.rain_overlap_min, slot.duration_min, slot.before_rain, onset_hour),
        wind_item(weather, weather_source),
        uv_item(weather, weather_source),
        time_item(slot.is_dark, features, weather_source),
        lighting,
        shade,
        traffic_item(course, slot.is_dark),
        surface_item(course, wet),
        facilities_item(course),
        park_item(course),
    )
    hot = weather.apparent_temperature >= features.comfort_high - 2 and not slot.is_dark
    weights = {**(WEIGHTS_DARK if slot.is_dark else WEIGHTS_DAY)}
    if hot:
        weights["shade"] = 0.15
    score = _weighted_score(items, weights)
    return _summarize(items, score, _blocking_reasons(course, slot, features, shade, lighting))


def assess_conditions(hour: HourWeather, features: PetFeatures, weather_source: str = FORECAST) -> SafetyAssessment:
    """코스와 무관하게 지금 날씨와 시간대가 산책에 어떤지 평가한다."""
    is_dark = not hour.is_day
    items = (
        temperature_item(hour, features, weather_source),
        rain_item(hour, weather_source),
        wind_item(hour, weather_source),
        uv_item(hour, weather_source),
        time_item(is_dark, features, weather_source),
    )
    return _summarize(items, _weighted_score(items, WEIGHTS_WEATHER_ONLY), ())


def assessment_payload(assessment: SafetyAssessment) -> dict:
    return {
        "score": assessment.score,
        "level": assessment.level,
        "items": [
            {
                "key": item.key,
                "label": item.label,
                "status": item.status,
                "score": item.score,
                "value": item.value,
                "source": item.source,
                "source_label": item.source_label,
                "detail": item.detail,
            }
            for item in assessment.items
        ],
        "risks": list(assessment.risks),
        "blocked_reasons": list(assessment.blocked_reasons),
        "unverified": list(assessment.unverified),
        "penalty": assessment.penalty,
        "disclaimer": assessment.disclaimer,
    }
