# PawPath API 명세

기본 주소는 `http://localhost:8000/api`입니다. 서버 실행 중에는 `http://localhost:8000/docs`에서 Swagger UI로 직접 호출할 수 있습니다.

- 모든 요청과 응답은 JSON입니다.
- 시각은 서비스 지역(Asia/Seoul) 기준이며 타임존 표기가 없습니다. 예: `2026-10-31T16:00:00`
- MVP는 인증 없이 기본 보호자 1명으로 동작합니다.

## 공통 오류

| 상태 | 의미 | 응답 |
|---|---|---|
| 404 | 대상 없음 | `{"detail": "반려동물을 찾을 수 없습니다"}` |
| 409 | 이미 피드백을 남긴 산책 | `{"detail": "이미 피드백을 남긴 산책입니다"}` |
| 422 | 입력값 오류 | FastAPI 검증 오류 형식 |

## 반려동물

### `POST /pets` · `PUT /pets/{pet_id}`

```json
{
  "name": "두부",
  "breed": "말티즈",
  "age_years": 5,
  "weight_kg": 4.2,
  "size": "small",
  "activity_level": "medium",
  "personality": "timid",
  "path_preference": "familiar",
  "heat_sensitivity": "medium",
  "novelty_reaction": "anxious"
}
```

| 필드 | 값 |
|---|---|
| `size` | `small`, `medium`, `large` |
| `activity_level`, `heat_sensitivity` | `low`, `medium`, `high` |
| `personality` | `active`(활발함), `timid`(소심함), `curious`(호기심 많음) |
| `path_preference` | `familiar`(익숙한 길), `new`(새로운 길) |
| `novelty_reaction` | `calm`, `cautious`, `anxious` |
| `preferred_distance_km` | 선택. 선호 거리 |
| `preferred_time_bucket` | 선택. `morning`, `lunch`, `afternoon`, `evening` |

`PUT`에서 선택 항목을 보내지 않으면 저장된 값을 유지합니다. `null`을 보내면 지웁니다.

응답은 입력값에 `id`, `feedback_total`, `created_at`, `updated_at`이 더해진 객체입니다. `POST`는 201, `PUT`은 200을 돌려줍니다.

### `GET /pets` · `GET /pets/{pet_id}`

반려동물 목록 또는 한 마리를 돌려줍니다.

### `GET /pets/{pet_id}/insights`

마이페이지 분석 자료입니다. 산책 통계(`stats`), 코스별 방문과 선호도(`courses`), 학습된 특성 가중치(`attributes`), 시간대 선호(`time_preferences`), 선호도 변화(`affinity_history`), 추천 결과 변화(`recommendation_history`)를 포함합니다.

## 보호자 일정

### `GET /schedule` · `PUT /schedule`

```json
{
  "available_windows": [{ "start_hour": 16, "end_hour": 20 }],
  "preferred_duration_min": 40,
  "walks_per_day": 1
}
```

`end_hour`는 미포함입니다. 겹치거나 이어지는 시간대는 저장할 때 합칩니다.

## 날씨

공통 쿼리 `scenario`: `live`(기본), `rain_later`, `rain_now`, `heatwave`, `cold`, `heavy_rain`. `live` 외에는 시연용이며 응답의 `is_mock`이 `true`입니다.

### `GET /weather/current`

쿼리 `pet_id`(선택)를 주면 해당 반려동물 기준 날씨 적합도를 함께 돌려줍니다.

```json
{
  "source": "open-meteo",
  "scenario": "live",
  "is_mock": false,
  "notice": null,
  "current": {
    "time": "2026-10-30T23:00:00",
    "temperature": 12.4,
    "apparent_temperature": 11.7,
    "precipitation_probability": 33.0,
    "precipitation_mm": 0.0,
    "humidity": 84.0,
    "wind_speed": 1.12,
    "uv_index": 0.0,
    "is_day": false
  },
  "condition": "선선함",
  "walk_comfort_hint": "지금 두부 기준 날씨 적합도 99점"
}
```

`source` 값은 `open-meteo`, `mock`, `mock-fallback`(API 실패), `scenario:*`입니다.

### `GET /weather/forecast`

쿼리 `hours`(1~48, 기본 24). 시간별 예보를 `hours` 배열로 돌려줍니다.

## 산책 코스

### `GET /courses` · `GET /courses/{course_id}`

코스 정보, 경로(`route`: `[위도, 경도]` 배열), 시설(`facilities`), 출처(`data_sources`)를 돌려줍니다.

### `POST /courses/{course_id}/approach`

현재 위치에서 코스 출발점까지의 도보 경로입니다. 좌표가 접근 로그에 남지 않도록 쿼리가 아닌 본문으로 받으며, 저장하지 않습니다.

```json
{ "latitude": 37.556, "longitude": 126.9105 }
```

```json
{
  "mode": "routed",
  "distance_m": 422.6,
  "duration_min": 7,
  "route": [[37.556, 126.9105], [37.5545, 126.9065]],
  "notice": null
}
```

| `mode` | 의미 | `route` |
|---|---|---|
| `routed` | OSRM 도보 경로 | 경로 좌표 |
| `straight` | 길찾기 실패 또는 미사용. `notice`에 안내 문구 | 현재 위치와 출발점 |
| `too_far` | `ROUTING_MAX_DISTANCE_KM` 초과. 외부 길찾기를 호출하지 않음 | 빈 배열 |

### `GET /courses/{course_id}/nearby`

코스 경로 주변 시설입니다. 미리 수집한 OSM 자료에서 찾으며 사용자 위치를 받지 않습니다.

쿼리: `radius_m`(50~1000, 기본 300), `types`(쉼표 구분: `park`, `dog_park`, `veterinary`, `pet_friendly`, `pet_shop`, `drinking_water`, `toilets`, `convenience`)

```json
{
  "course_id": 1,
  "radius_m": 300,
  "source": "OpenStreetMap",
  "collected_on": "2026-10-31",
  "unavailable_types": [],
  "notice": "지도에 기록된 장소만 보여 줘요. 없는 것처럼 보여도 실제로는 있을 수 있어요.",
  "places": [
    { "type": "park", "label": "공원", "name": "망원초록길", "lat": 37.551, "lng": 126.902, "distance_m": 18, "note": null }
  ]
}
```

`pet_friendly`는 OSM 표시 기준이며 `note`에 실제 동반 여부를 확인하라는 안내가 붙습니다.

## 경로

### `POST /routes/walking`

두 지점 사이의 도보 경로입니다. 코스를 벗어났을 때 돌아갈 길을 찾는 데 씁니다. 응답은 `/courses/{id}/approach`와 같습니다.

```json
{ "from_latitude": 37.55, "from_longitude": 126.9, "to_latitude": 37.551, "to_longitude": 126.9 }
```

### `POST /routes/alternative`

산책 중 환경을 다시 평가합니다. 위치는 없어도 됩니다.

```json
{ "pet_id": 1, "course_id": 1, "latitude": 37.55, "longitude": 126.9, "progress_m": 600, "weather_scenario": "live" }
```

응답(일부 생략):

```json
{
  "status": "shorten",
  "action": "return_to_start",
  "reasons": ["지금 비가 내리거나 내릴 가능성이 높아요."],
  "remaining_m": 980,
  "remaining_min": 16,
  "checked_at": "2026-10-31T16:10:00",
  "cache_minutes": 30,
  "data_limit": "시간별 예보로 판단해요. 실시간 강수 감지가 아니니 하늘 상태도 함께 살펴 주세요.",
  "weather": { "source": "open-meteo", "scenario": "live", "is_mock": false, "notice": null },
  "assessment": {},
  "return_route": { "mode": "routed", "distance_m": 280, "duration_min": 5, "route": [], "notice": null },
  "location_notice": null,
  "alternatives": [
    { "course_id": 3, "name": "...", "distance_km": 1.2, "duration_min": 20, "from_here_m": 300, "safety_score": 82, "safety_level": "caution", "reason": "..." }
  ]
}
```

| 값 | 의미 |
|---|---|
| `status` | `continue` 계속, `shorten` 줄이기, `return_now` 즉시 복귀, `unknown` 예보 없음 |
| `action` | `continue`, `return_to_start`, `finish_course`(마저 걷는 편이 짧음), `no_location`(위치 없음), `no_walking_route`(너무 멀음) |

## 안전 지수

### `GET /safety`

쿼리: `pet_id`, `course_id`(선택), `scenario`(선택). `course_id`가 없으면 날씨와 시간대만 평가합니다.

`assessment` 형식:

```json
{
  "score": 83.0,
  "level": "caution",
  "items": [
    { "key": "lighting", "label": "조명", "status": "unverified", "score": 55.0, "value": "확인 불가 (추정: 일부 구간 조명)", "source": "estimated", "source_label": "팀 추정", "detail": "조명 기록이 부족해 확인할 수 없어요. 현장을 확인해 주세요." }
  ],
  "risks": ["오후 5시부터 비 예보가 있어요. 늦어지면 일찍 돌아오세요."],
  "blocked_reasons": [],
  "unverified": ["조명", "그늘", "노면"],
  "penalty": 1.5,
  "disclaimer": "안전 점수는 환경 위험을 비교하는 참고값이에요. 의학적, 절대적 안전을 보장하지 않아요."
}
```

| 값 | 의미 |
|---|---|
| `level` | `good`, `caution`, `danger`, `blocked`(추천 제외) |
| `items[].status` | `ok`, `caution`, `danger`, `unverified`(확인 불가) |
| `items[].source` | `forecast` 예보, `demo` 모의, `observed` OSM 기록, `estimated` 팀 추정, `unknown` 데이터 없음 |

## 추천

### `POST /recommendations`

```json
{ "pet_id": 1, "weather_scenario": "rain_later" }
```

응답(201, 일부 생략):

```json
{
  "id": 12,
  "created_at": "2026-10-30T23:00:00",
  "pet_id": 1,
  "pet_name": "두부",
  "walkable": true,
  "weather": { "source": "scenario:rain_later", "scenario": "rain_later", "is_mock": true, "notice": "시연용 시나리오: 곧 비가 오는 날" },
  "weights": { "weather": 0.25, "personality": 0.25, "activity": 0.15, "schedule": 0.15, "safety": 0.1, "preference": 0.1 },
  "learning": { "feedback_total": 0, "is_personalized": false },
  "time_recommendation": {
    "recommended_duration_min": 30,
    "best_slots": [{ "start": "2026-10-31T16:00:00", "end": "2026-10-31T16:30:00", "score": 88.0, "before_rain": true }],
    "slots": []
  },
  "courses": [
    {
      "rank": 1,
      "course_id": 1,
      "name": "망원초록길 공원 코스",
      "distance_km": 1.58,
      "duration_min": 25,
      "total_score": 90.0,
      "baseline_score": 90.0,
      "learning_delta": 0.0,
      "rank_change": 0,
      "recommended_time": {},
      "safety": {},
      "factors": [
        { "key": "weather", "label": "날씨 적합도", "score": 100.0, "weight": 0.25, "contribution": 25.0, "evidence": ["16시 체감 21°C, 강수 확률 20%"] }
      ],
      "reason": {
        "summary": "낯선 길을 싫어하는 두부를 위해 익숙한 공원 코스를 골랐어요. 비가 오기 전 짧게 다녀올 수 있어요.",
        "details": []
      },
      "cautions": []
    }
  ],
  "blocked_reasons": [],
  "indoor_alternatives": [],
  "disclaimer": "날씨 적합도는 수의학적 안전 진단이 아니에요. 건강 상태와 현장 상황을 먼저 살펴 주세요."
}
```

코스마다 다음 필드가 더 있습니다.

| 필드 | 내용 |
|---|---|
| `score_breakdown` | 6개 평가 묶음: 반려동물 적합도, 사용자 선호도, 날씨, 안전, 시간, 과거 만족도 |
| `factors` | 세부 항목 7개와 근거 |
| `safety_assessment` | 안전 지수 (`GET /safety`와 같은 형식) |
| `alternative` | 위험 수준이 실제로 낮은 대체 코스, 없으면 `null` |
| `other_cautions` | 안전 지수에 없는 주의사항 |
| `reason.llm_summary` | 사실 검증을 통과한 LLM 문장 (있을 때만) |

응답 최상위에는 `excluded_courses`(제외 코스와 이유), `learning.mode`(`rule_based`, `personalized`), `explanation_engine`(`status`: `disabled`, `pending`, `ok`, `rejected`, `failed`)이 있습니다.

`learning_delta`와 `rank_change`는 같은 날씨에서 학습 상태를 비운 기준선과의 차이입니다. 모든 시간대가 부적합하면 `walkable`이 `false`이고 `courses`가 비며, `blocked_reasons`와 `indoor_alternatives`를 채웁니다.

### `POST /recommendations/{recommendation_id}/explain`

추천 이유를 LLM 문장으로 보강해 추천 전체를 돌려줍니다. 점수와 순위는 바뀌지 않습니다. LLM이 꺼져 있거나 실패하면 그대로 돌려줍니다.

### `GET /recommendations/{recommendation_id}`

저장된 추천을 돌려줍니다.

### `GET /recommendations?pet_id=1&limit=10`

최신순 추천 목록입니다.

## 산책 기록

### `POST /walks`

```json
{ "pet_id": 1, "course_id": 3, "recommendation_id": 12, "duration_min": 20, "started_at": "2026-10-31T16:00:00" }
```

`recommendation_id`, `started_at`은 선택입니다. `started_at`이 없으면 지금 끝난 산책으로 기록합니다. 코스 방문 수가 함께 올라갑니다.

선택 필드: `tracking_source`(`gps`, `manual`, `simulation`, 기본 `manual`), `distance_km`(실제 걸은 거리, 없으면 코스 거리). `simulation`은 활동 통계에서 제외합니다.

### `GET /walks?pet_id=1`

최신순 산책 기록과 각 산책의 피드백입니다. `tracking_source`, `is_simulated`를 함께 돌려줍니다.

### `GET /walks/report?pet_id=1&week_offset=0`

주간 활동 리포트입니다. `week_offset`은 0이 이번 주, -1이 지난주입니다(최대 -52). 시연용 산책은 통계에서 빼고 `simulated_walks_excluded`로 건수만 알려 줍니다.

| 필드 | 내용 |
|---|---|
| `summary` | 횟수, 누적 거리, 누적 시간, 평균 시간, 평균 만족도 |
| `previous_week`, `change` | 지난주 값과 증감 (`percent`는 지난주 기록이 없으면 `null`) |
| `daily` | 요일별 7일 기록 |
| `favorite_courses` | 많이 간 코스 |
| `satisfaction_trend` | 최근 피드백의 만족도 |
| `recommendation_vs_actual` | 추천 1위와 실제 선택 비교 |

## 피드백

### `POST /feedback`

```json
{
  "walk_id": 7,
  "walk_rating": 5,
  "pet_rating": 5,
  "difficulty": "just_right",
  "weather_rating": 5,
  "would_revisit": true,
  "memo": "꼬리를 흔들며 잘 걸었어요"
}
```

`difficulty`: `easy`, `just_right`, `hard`. 산책 1회당 1건만 받으며, 저장과 동시에 학습 상태를 갱신합니다. 응답의 `affinity_before`, `affinity_after`로 선호도 변화를 알 수 있습니다.

### `GET /feedback/{pet_id}`

해당 반려동물의 피드백 목록(최신순)입니다.

## 시스템

### `GET /health`

`{"status": "ok", "service": "PawPath"}`
