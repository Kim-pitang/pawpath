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

공통 쿼리 `scenario`: `live`(기본), `rain_later`, `heatwave`, `cold`, `heavy_rain`. `live` 외에는 시연용이며 응답의 `is_mock`이 `true`입니다.

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

`learning_delta`와 `rank_change`는 같은 날씨에서 학습 상태를 비운 기준선과의 차이입니다. 모든 시간대가 부적합하면 `walkable`이 `false`이고 `courses`가 비며, `blocked_reasons`와 `indoor_alternatives`를 채웁니다.

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

### `GET /walks?pet_id=1`

최신순 산책 기록과 각 산책의 피드백입니다.

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
