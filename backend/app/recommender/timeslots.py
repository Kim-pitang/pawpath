"""시간대 점수 계산.

보호자 가능 시간 안의 각 출발 시각을 날씨, 산책 길이, 일조, 학습된 시간대 선호로 평가한다.
"""
from collections.abc import Mapping
from datetime import datetime, timedelta

from app.recommender.preference import preferred_time_match, time_bucket_score
from app.recommender.types import (
    HourWeather,
    PetFeatures,
    PreferenceState,
    Schedule,
    SlotEvaluation,
    TimeRecommendation,
    TimeWindow,
)

SLOT_WEIGHTS = {"comfort": 0.55, "fit": 0.15, "daylight": 0.10, "learned": 0.10, "soon": 0.10}

RAIN_PROB_THRESHOLD = 60.0
RAIN_MM_THRESHOLD = 0.3
HEAVY_RAIN_MM = 3.0
UNSAFE_WIND_MS = 14.0
BEFORE_RAIN_HORIZON = timedelta(hours=3)
RAIN_LOOKAHEAD_HOURS = 12
MIN_WALK_GAP = timedelta(hours=3)


def is_rainy(hour: HourWeather) -> bool:
    return hour.precipitation_mm >= RAIN_MM_THRESHOLD or hour.precipitation_probability >= RAIN_PROB_THRESHOLD


def unsafe_reason(hour: HourWeather, features: PetFeatures) -> str | None:
    """이 시간에는 산책을 권하지 않는 이유. 안전 진단이 아니라 보수적인 제외 기준이다."""
    if hour.precipitation_mm >= HEAVY_RAIN_MM:
        return f"시간당 {hour.precipitation_mm:.1f}mm의 강한 비 예보"
    if hour.apparent_temperature >= features.unsafe_heat:
        return f"체감 {hour.apparent_temperature:.0f}°C의 더위"
    if hour.apparent_temperature <= features.unsafe_cold:
        return f"체감 {hour.apparent_temperature:.0f}°C의 추위"
    if hour.wind_speed >= UNSAFE_WIND_MS:
        return f"초속 {hour.wind_speed:.0f}m의 강풍"
    return None


def hour_comfort(hour: HourWeather, features: PetFeatures) -> float:
    """한 시간의 날씨를 반려동물 기준 0~100점으로 평가한다."""
    apparent = hour.apparent_temperature
    if apparent > features.comfort_high:
        temp = 100 - (apparent - features.comfort_high) * 100 / (features.unsafe_heat - features.comfort_high)
    elif apparent < features.comfort_low:
        temp = 100 - (features.comfort_low - apparent) * 100 / (features.comfort_low - features.unsafe_cold)
    else:
        temp = 100.0
    if apparent > features.comfort_high - 2 and hour.humidity > 70:
        temp -= 10

    rain = 100 - max(0.0, hour.precipitation_probability - 30) * 0.7 - min(60.0, hour.precipitation_mm * 40)

    wind = 100.0 if hour.wind_speed <= 5 else 100 - (hour.wind_speed - 5) * 70 / 9

    uv = 100.0
    if hour.is_day and hour.uv_index is not None and hour.uv_index > 5:
        uv = 100 - (hour.uv_index - 5) * 10

    score = 0.5 * temp + 0.35 * rain + 0.1 * wind + 0.05 * uv
    if rain < 40:
        score = min(score, rain + 15)
    return max(0.0, min(100.0, score))


def weather_ideal_factor(hour: HourWeather, features: PetFeatures) -> float:
    """더위와 추위가 심할수록 권장 산책량을 줄인다."""
    if hour.apparent_temperature < features.comfort_low - 5 or hour.apparent_temperature > features.comfort_high + 5:
        return 0.6
    if hour.apparent_temperature < features.comfort_low or hour.apparent_temperature > features.comfort_high:
        return 0.8
    return 1.0


def candidate_starts(now: datetime, windows: tuple[TimeWindow, ...]) -> list[tuple[datetime, TimeWindow]]:
    """지금부터 24시간 안에 있는, 가능 시간대의 정시 출발 후보."""
    first = now if now.minute == 0 else now.replace(minute=0) + timedelta(hours=1)
    candidates: list[tuple[datetime, TimeWindow]] = []
    for offset in range(24):
        start = first + timedelta(hours=offset)
        for window in windows:
            if window.start_hour <= start.hour < window.end_hour:
                candidates.append((start, window))
                break
    return candidates


def _span_hours(start: datetime, duration_min: int) -> list[tuple[datetime, int]]:
    """산책 구간을 (정시, 해당 시간에 걸친 분) 목록으로 나눈다."""
    spans: list[tuple[datetime, int]] = []
    cursor = start
    remaining = duration_min
    while remaining > 0:
        hour_start = cursor.replace(minute=0)
        used = min(remaining, 60 - cursor.minute)
        spans.append((hour_start, used))
        cursor += timedelta(minutes=used)
        remaining -= used
    return spans


def evaluate_slot(
    start: datetime,
    duration_min: int,
    window: TimeWindow,
    forecast: Mapping[datetime, HourWeather],
    features: PetFeatures,
    preferences: PreferenceState,
    now: datetime,
) -> SlotEvaluation | None:
    """출발 시각 하나를 평가한다. 예보가 없으면 None을 돌려준다."""
    spans = _span_hours(start, duration_min)
    hours = [(forecast.get(hour), minutes) for hour, minutes in spans]
    if any(hour is None for hour, _ in hours):
        return None

    first_hour = hours[0][0]
    comforts = [(hour_comfort(hour, features), minutes) for hour, minutes in hours]
    average = sum(score * minutes for score, minutes in comforts) / duration_min
    comfort = 0.7 * average + 0.3 * min(score for score, _ in comforts)

    unsafe = next((reason for hour, _ in hours if (reason := unsafe_reason(hour, features))), None)
    rain_overlap = sum(minutes for hour, minutes in hours if is_rainy(hour))

    end = start + timedelta(minutes=duration_min)
    rain_onset = None
    for offset in range(RAIN_LOOKAHEAD_HOURS + 1):
        probe = start.replace(minute=0) + timedelta(hours=offset)
        hour = forecast.get(probe)
        if hour is not None and is_rainy(hour):
            rain_onset = probe
            break
    before_rain = rain_overlap == 0 and rain_onset is not None and rain_onset - end <= BEFORE_RAIN_HORIZON

    window_end = start.replace(hour=0, minute=0) + timedelta(hours=window.end_hour)
    fits_window = end <= window_end
    if fits_window:
        fit = 100.0
    else:
        available = max(0.0, (window_end - start).total_seconds() / 60)
        fit = 100 * (available / duration_min) ** 2

    is_dark = not all(hour.is_day for hour, _ in hours)
    if is_dark:
        daylight = 40.0 if features.life_stage == "senior" or features.crowd_tolerance < 0.3 else 70.0
    else:
        daylight = 100.0

    learned = time_bucket_score(preferences, start.hour)
    time_match = preferred_time_match(features.preferred_time_bucket, start.hour)
    if time_match is not None:
        learned = (learned + time_match) / 2
    hours_ahead = (start - now).total_seconds() / 3600
    soon = max(0.0, 100 - hours_ahead * 100 / 24)

    components = {"comfort": comfort, "fit": fit, "daylight": daylight, "learned": learned, "soon": soon}
    score = sum(SLOT_WEIGHTS[key] * value for key, value in components.items())
    score -= rain_overlap / duration_min * 30

    return SlotEvaluation(
        start=start,
        end=end,
        duration_min=duration_min,
        window=window,
        weather=first_hour,
        score=round(max(0.0, min(100.0, score)), 1),
        comfort=round(comfort, 1),
        components={key: round(value, 1) for key, value in components.items()},
        unsafe_reason=unsafe,
        rain_overlap_min=rain_overlap,
        rain_onset=rain_onset,
        before_rain=before_rain,
        is_dark=is_dark,
        fits_window=fits_window,
        ideal_factor=weather_ideal_factor(first_hour, features),
    )


def recommended_walk_minutes(features: PetFeatures, schedule: Schedule) -> int:
    """보호자의 산책 횟수와 희망 시간을 반영한 1회 권장 시간."""
    per_walk = features.ideal_walk_min / max(1, schedule.walks_per_day)
    return max(10, min(schedule.preferred_duration_min, _round_to_5(per_walk)))


def _round_to_5(minutes: float) -> int:
    return int(round(minutes / 5) * 5)


def _pick_best(slots: list[SlotEvaluation], count: int) -> tuple[SlotEvaluation, ...]:
    """점수 순으로, 서로 충분히 떨어진 시간대를 희망 횟수만큼 고른다."""
    picked: list[SlotEvaluation] = []
    for slot in sorted((s for s in slots if not s.unsafe_reason), key=lambda s: (-s.score, s.start)):
        if all(abs(slot.start - other.start) >= MIN_WALK_GAP for other in picked):
            picked.append(slot)
        if len(picked) == count:
            break
    return tuple(sorted(picked, key=lambda s: s.start))


def recommend_times(
    now: datetime,
    forecast: Mapping[datetime, HourWeather],
    features: PetFeatures,
    schedule: Schedule,
    preferences: PreferenceState,
) -> TimeRecommendation:
    base_minutes = recommended_walk_minutes(features, schedule)
    slots: list[SlotEvaluation] = []
    for start, window in candidate_starts(now, schedule.windows):
        slot = evaluate_slot(start, base_minutes, window, forecast, features, preferences, now)
        if slot is None:
            continue
        # 추위와 더위가 심하면 시간을 줄이고, 줄인 시간으로 다시 평가한다.
        adjusted = max(10, _round_to_5(base_minutes * slot.ideal_factor))
        if slot.rain_onset is not None and slot.rain_onset > start:
            gap = int((slot.rain_onset - start).total_seconds() // 60)
            adjusted = max(10, min(adjusted, gap))
        if adjusted != base_minutes:
            slot = evaluate_slot(start, adjusted, window, forecast, features, preferences, now) or slot
        slots.append(slot)

    best = _pick_best(slots, schedule.walks_per_day)
    duration = best[0].duration_min if best else base_minutes
    return TimeRecommendation(recommended_duration_min=duration, best_slots=best, all_slots=tuple(slots))
