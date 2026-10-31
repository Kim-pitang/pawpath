"""추천 이유와 주의사항 생성.

문장은 프로필, 코스 데이터, 날씨, 계산 결과에 있는 사실로만 만든다.
코스 데이터에 없는 시설이나 확인되지 않은 안전 정보는 언급하지 않는다.
"""
from app.recommender.course_scoring import familiarity, is_disliked
from app.recommender.text import hour_label
from app.recommender.types import (
    CourseData,
    CoursePreference,
    Explanation,
    FactorScore,
    PetFeatures,
    PetProfile,
    PreferenceState,
    SlotEvaluation,
)

SHORT_WALK_MIN = 40
LIKED_AFFINITY = 60.0
DISCLAIMER = "날씨 적합도는 수의학적 안전 진단이 아니에요. 건강 상태와 현장 상황을 먼저 살펴 주세요."


def has_final_consonant(word: str) -> bool:
    """마지막 글자에 받침이 있는지 판별한다. 한글이 아니면 받침 없음으로 본다."""
    if not word:
        return False
    code = ord(word[-1]) - 0xAC00
    return 0 <= code <= 11171 and code % 28 != 0


def object_particle(name: str) -> str:
    return "을" if has_final_consonant(name) else "를"


def topic_particle(name: str) -> str:
    return "은" if has_final_consonant(name) else "는"


def course_kind(course: CourseData) -> str:
    if course.has_park:
        return "공원"
    if "river" in course.scenery_tags:
        return "강변"
    if "forest" in course.scenery_tags:
        return "숲길"
    return "동네"


def _pet_sentence(pet: PetProfile, features: PetFeatures, course: CourseData, state: PreferenceState) -> str:
    name = pet.name
    target = f"{name}{object_particle(name)} 위해"
    kind = course_kind(course)
    current = state.courses.get(course.id, CoursePreference())
    liked = current.feedback_count > 0 and current.affinity >= LIKED_AFFINITY
    known = familiarity(course, state) >= 0.5

    if is_disliked(current):
        return f"{name}의 지난 만족도는 낮았지만 오늘 다른 조건이 잘 맞아 후보에 올렸어요."

    if features.novelty_tolerance < 0.4:
        if liked:
            return f"낯선 길을 싫어하는 {target} 지난번 만족도가 높았던 익숙한 {kind} 코스를 다시 골랐어요."
        if known:
            return f"낯선 길을 싫어하는 {target} 익숙한 {kind} 코스를 골랐어요."
        if course.crowd_level == "low":
            return f"낯선 길을 싫어하는 {target} 처음이어도 부담이 적은 한적한 {kind} 코스를 골랐어요."
        return f"{name}에게는 낯선 {kind} 코스지만 다른 조건이 잘 맞아 골랐어요."

    if features.novelty_tolerance > 0.6:
        if liked:
            return f"{name}{topic_particle(name)} 새로운 길을 좋아하지만, 지난번 만족도가 높았던 {kind} 코스라 골랐어요."
        if current.visit_count == 0:
            return f"새로운 길을 좋아하는 {target} 아직 안 가 본 {kind} 코스를 골랐어요."
        return f"새로운 길을 좋아하는 {target} 분위기가 다른 {kind} 코스를 골랐어요."

    if liked:
        return f"지난번 {name}의 만족도가 높았던 {kind} 코스를 골랐어요."
    return f"{name}의 활동량과 성향에 잘 맞는 {kind} 코스를 골랐어요."


def _lighting_recorded(course: CourseData) -> bool:
    """조명이 있다고 말할 근거가 있는지. 팀 추정값은 근거로 치지 않는다."""
    lit = course.environment.get("lit") or {}
    known = lit.get("yes", 0.0) + lit.get("no", 0.0)
    return known >= 0.5 and lit.get("yes", 0.0) / known >= 0.7


def _weather_sentence(course: CourseData, slot: SlotEvaluation, features: PetFeatures) -> str:
    apparent = slot.weather.apparent_temperature
    if slot.rain_overlap_min > 0:
        return "산책 중 비 예보가 있으니 우비를 챙기면 좋아요."
    if slot.before_rain:
        return "비가 오기 전 짧게 다녀올 수 있어요." if course.duration_min <= SHORT_WALK_MIN else "비가 오기 전에 다녀올 수 있어요."
    if apparent > features.comfort_high:
        if course.shade_level >= 0.6:
            return "더운 날이라 그늘이 많을 것으로 보이는 길로 골랐어요."
        return f"더운 날이라 비교적 덜 더운 {hour_label(slot.start.hour)}로 맞췄어요."
    if apparent < features.comfort_low:
        return f"추운 날이라 약 {course.duration_min}분 코스로 무리하지 않게 다녀올 수 있어요."
    if slot.is_dark and _lighting_recorded(course):
        return f"{hour_label(slot.start.hour)}는 해가 진 뒤라 조명 기록이 있는 길로 골랐어요."
    return f"{hour_label(slot.start.hour)}는 체감 {apparent:.0f}°C로 산책하기 좋아요."


def build_details(factors: tuple[FactorScore, ...]) -> tuple[str, ...]:
    """기여도가 큰 항목 순으로 근거를 정리한다."""
    ranked = sorted(factors, key=lambda factor: -factor.contribution)
    return tuple(f"{factor.label} {factor.score:.0f}점: {', '.join(factor.evidence)}" for factor in ranked)


def non_environment_cautions(
    pet: PetProfile,
    features: PetFeatures,
    course: CourseData,
    slot: SlotEvaluation,
) -> tuple[str, ...]:
    """안전 지수에 나오지 않는, 반려동물 특성과 일정에 관한 주의사항."""
    cautions: list[str] = []
    if not slot.fits_window:
        cautions.append(f"코스를 다 돌면 가능 시간({slot.window.end_hour}시)을 넘겨요.")
    if course.crowd_level == "high" and features.crowd_tolerance < 0.5:
        cautions.append(f"사람이 많은 코스라 {pet.name}{topic_particle(pet.name)} 긴장할 수 있어요.")
    if course.difficulty != "easy" and features.life_stage != "adult":
        cautions.append("오르막이 있어 관절에 부담이 될 수 있어요. 천천히 걸어 주세요.")
    return tuple(cautions)


def build_cautions(
    pet: PetProfile,
    features: PetFeatures,
    course: CourseData,
    slot: SlotEvaluation,
) -> tuple[str, ...]:
    cautions: list[str] = []
    weather = slot.weather

    if slot.rain_overlap_min > 0:
        cautions.append(f"산책 시간 중 {slot.rain_overlap_min}분이 비 예보와 겹쳐요.")
    elif slot.rain_onset is not None and slot.before_rain:
        cautions.append(f"{hour_label(slot.rain_onset.hour)}부터 비 예보가 있어요. 늦어지면 일찍 돌아오세요.")
    if not course.is_paved and (slot.rain_overlap_min > 0 or weather.precipitation_probability >= 50):
        cautions.append("비포장 구간이 젖으면 미끄러울 수 있어요.")
    if weather.apparent_temperature > features.comfort_high:
        cautions.append("더운 시간에는 노면이 뜨거울 수 있어요. 손등으로 먼저 확인하고 물을 챙겨 주세요.")
    if weather.apparent_temperature < features.comfort_low:
        cautions.append(f"체감 {weather.apparent_temperature:.0f}°C로 추워요. 산책 시간을 줄이고 체온을 살펴 주세요.")
    if weather.is_day and weather.uv_index is not None and weather.uv_index >= 6:
        cautions.append(f"자외선 지수 {weather.uv_index:.0f}로 높아요.")
    if slot.is_dark and course.lighting in ("poor", "partial", "unknown"):
        cautions.append("해가 진 뒤 일부 구간이 어두울 수 있어요. 조명이나 반사 용품을 챙겨 주세요.")
    cautions.extend(non_environment_cautions(pet, features, course, slot))
    cautions.append(DISCLAIMER)
    return tuple(cautions)


def build_explanation(
    pet: PetProfile,
    features: PetFeatures,
    course: CourseData,
    slot: SlotEvaluation,
    factors: tuple[FactorScore, ...],
    state: PreferenceState,
) -> Explanation:
    summary = f"{_pet_sentence(pet, features, course, state)} {_weather_sentence(course, slot, features)}"
    return Explanation(
        summary=summary,
        details=build_details(factors),
        cautions=build_cautions(pet, features, course, slot),
        other_cautions=non_environment_cautions(pet, features, course, slot),
    )
