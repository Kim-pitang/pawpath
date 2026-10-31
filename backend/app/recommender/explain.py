"""추천 이유와 주의사항 생성.

문장은 프로필, 코스 데이터, 날씨, 계산 결과에 있는 사실로만 만든다.
코스 데이터에 없는 시설이나 확인되지 않은 안전 정보는 언급하지 않는다.
"""
from app.recommender.course_scoring import familiarity, is_disliked
from app.recommender.profile import adjusted_ideal_km
from app.recommender.safety import SOURCE_LABELS, UNAVAILABLE
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


def _weather_sentence(course: CourseData, slot: SlotEvaluation, features: PetFeatures, weather_available: bool = True) -> str:
    apparent = slot.weather.apparent_temperature
    if not weather_available:
        return "실제 날씨를 받지 못해 날씨는 고려하지 못했어요. 나가기 전에 하늘과 기온을 확인해 주세요."
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
    elif "difficulty" in course.unknown and features.life_stage != "adult":
        cautions.append("경사 정보가 없는 코스예요. 오르막이 있으면 천천히 걸어 주세요.")
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
    weather_available: bool = True,
    exploration: bool = False,
    similar_to: str | None = None,
    basis: tuple[dict, ...] = (),
) -> Explanation:
    summary = f"{_pet_sentence(pet, features, course, state)} {_weather_sentence(course, slot, features, weather_available)}"
    if exploration:
        summary += " 다녀온 코스만 이어지지 않게 아직 안 가 본 코스를 하나 넣었어요."
    other = non_environment_cautions(pet, features, course, slot)
    if similar_to:
        other = (*other, f"{similar_to} 코스와 길이 많이 겹쳐요. 다른 후보가 부족해 함께 올렸어요.")
    cautions = build_cautions(pet, features, course, slot)
    if not weather_available:
        # 모의 날씨로 만든 비, 더위, 추위 주의사항은 사실이 아니므로 빼고 날씨 확인을 당부한다.
        cautions = (*other, "실제 날씨를 받지 못했어요. 나가기 전에 날씨를 확인해 주세요.", DISCLAIMER)
    elif similar_to:
        cautions = (*cautions[:-1], other[-1], cautions[-1])
    return Explanation(
        summary=summary,
        details=build_details(factors),
        cautions=cautions,
        other_cautions=other,
        basis=basis,
    )


LIFE_STAGE_TEXT = {"puppy": "어린 강아지", "adult": "성견", "senior": "노령견"}
ACTIVITY_TEXT = {"low": "적음", "medium": "보통", "high": "많음"}
LEVEL_TEXT = {"good": "양호", "caution": "주의", "danger": "위험", "blocked": "추천 제외"}


def _quality_text(quality: dict) -> str:
    shares = quality.get("shares", {})
    measured = shares.get("realtime", 0.0) + shares.get("observed", 0.0)
    parts = [f"예보·실측 {measured:.0%}", f"팀 추정 {shares.get('estimated', 0.0):.0%}"]
    if shares.get("demo"):
        parts.append(f"시연용 {shares['demo']:.0%}")
    parts.append(f"데이터 없음 {shares.get('missing', 0.0):.0%}")
    return ", ".join(parts)


def build_basis(
    pet: PetProfile,
    features: PetFeatures,
    course: CourseData,
    slot: SlotEvaluation,
    groups: tuple,
    assessment,
    state: PreferenceState,
    profile,
    weather_source: str,
) -> tuple[dict, ...]:
    """항목별 추천 근거. 계산에 실제로 쓴 값만 말하고, 쓰지 않은 항목은 '반영하지 않았다'고 밝힌다."""
    by_key = {group.key: group for group in groups}
    ideal_km, learned_share = adjusted_ideal_km(features.ideal_distance_km, profile)
    ideal = max(0.3, ideal_km * slot.ideal_factor)
    pet_text = (
        f"{pet.name}({LIFE_STAGE_TEXT[features.life_stage]}, 활동량 {ACTIVITY_TEXT[pet.activity_level]})의 오늘 권장 거리 약 {ideal:.1f}km에 "
        f"이 코스는 {course.distance_km:.1f}km예요."
    )
    if learned_share:
        pet_text += f" 권장 거리는 산책 {profile.completed_walks}회 기록으로 보정했어요."
    if course.difficulty != "easy":
        pet_text += " 오르막이 있어요."
    elif "difficulty" in course.unknown:
        pet_text += " 경사 정보는 없어요."

    # 성향 근거(익숙함, 혼잡도). 거리 근거는 위 문장에 이미 있다.
    pet_group = by_key.get("pet_fit")
    traits = [line for line in (pet_group.evidence if pet_group else ()) if "권장" not in line and "오르막" not in line]
    if traits:
        pet_text += " " + ", ".join(traits) + "."

    user = by_key.get("user_preference")
    user_text = "; ".join(user.evidence) if user and user.available else "선호 거리와 시간 입력이 없어 반영하지 않았어요."

    time_group = by_key.get("distance_time")
    time_text = f"{hour_label(slot.start.hour)} 출발 약 {course.duration_min}분. " + ", ".join(time_group.evidence if time_group else ())

    if weather_source == UNAVAILABLE:
        weather_text = "실제 날씨를 받지 못해 반영하지 않았어요."
    else:
        weather = slot.weather
        weather_text = f"{hour_label(slot.start.hour)} 체감 {weather.apparent_temperature:.0f}°C, 강수 확률 {weather.precipitation_probability:.0f}%, 바람 초속 {weather.wind_speed:.1f}m"

    risks = list(assessment.risks[:2])
    safety_text = f"안전 {assessment.score:.0f}점({LEVEL_TEXT[assessment.level]})."
    if risks:
        safety_text += " " + " ".join(risks)
    if assessment.unverified:
        safety_text += f" 확인 불가: {', '.join(assessment.unverified)}."

    feedback = by_key.get("feedback")
    if feedback and feedback.available:
        current = state.courses.get(course.id, CoursePreference())
        history_text = f"피드백 {state.feedback_total}건을 반영했어요(비중 {feedback.weight:.0%}). " + ", ".join(feedback.evidence)
        if current.visit_count:
            history_text += f" 이 코스에 {current.visit_count}번 다녀왔어요."
    else:
        history_text = "아직 피드백이 없어 과거 선호도는 반영하지 않았어요."

    basis = [
        {"key": "pet_fit", "label": "반려견 특성", "text": pet_text, "source": "반려견 프로필, 코스 데이터"},
        {"key": "user_preference", "label": "사용자 선호", "text": user_text, "source": user.source if user and user.available else "없음"},
        {"key": "distance_time", "label": "거리·시간", "text": time_text, "source": "보호자 일정"},
        {"key": "weather_env", "label": "날씨", "text": weather_text, "source": SOURCE_LABELS.get(weather_source, weather_source)},
        {"key": "safety", "label": "안전", "text": safety_text, "source": _quality_text(assessment.data_quality)},
        {"key": "feedback", "label": "과거 선호도", "text": history_text, "source": "산책 피드백" if feedback and feedback.available else "없음"},
    ]
    if assessment.warning:
        basis.insert(0, {"key": "warning", "label": "경고", "text": assessment.warning, "source": "안전 평가"})
    return tuple(basis)
