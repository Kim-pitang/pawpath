# PawPath API 명세

기본 주소는 `http://localhost:8000/api`입니다. 서버 실행 중에는 `http://localhost:8000/docs`에서 Swagger UI로 직접 호출할 수 있습니다.

- 모든 요청과 응답은 JSON입니다.
- 시각은 서비스 지역(Asia/Seoul) 기준이며 타임존 표기가 없습니다. 예: `2026-10-31T16:00:00`
- 로그인은 선택입니다. 로그인 세션 쿠키(`pawpath_session`)가 있으면 그 보호자의 데이터만 다루고, 없으면 시연 보호자(id 1)로 동작합니다. `AUTH_REQUIRED=true`면 로그인하지 않은 요청은 `401`입니다.
- 다른 보호자의 반려동물, 산책 기록, 산책길, 사진은 있어도 `404`로 응답합니다.

## 공통 오류

| 상태 | 의미 | 응답 |
|---|---|---|
| 404 | 대상 없음 | `{"detail": "반려동물을 찾을 수 없습니다"}` |
| 401 | 로그인이 필요하거나 세션이 만료됨 | `{"detail": "로그인이 만료되었어요. 다시 로그인해 주세요."}` (만료 시 쿠키 삭제) |
| 403 | 본인 재확인이 필요하거나 비밀번호가 틀림 | `{"detail": "탈퇴하려면 본인을 다시 확인해 주세요."}` |
| 503 | 탈퇴 기록을 남기지 못해 탈퇴를 취소함 | `{"detail": "탈퇴를 처리하지 못했어요. 지운 데이터는 없으니 잠시 뒤 다시 시도해 주세요."}` |
| 409 | 이미 피드백을 남긴 산책, 이미 쓰는 아이디, 사진 5장 초과 | `{"detail": "이미 피드백을 남긴 산책입니다"}` |
| 429 | 로그인을 연달아 틀림 | `{"detail": "로그인 시도가 너무 많아요. 10분 뒤에 다시 시도해 주세요."}` |
| 410 | 기간이 끝난 공유 링크 | `{"detail": "공유 기간이 끝난 링크예요"}` |
| 413 | 요청, GPX 파일, 사진이 너무 큼 | `{"detail": "파일이 너무 커요. 10MB까지 가져올 수 있어요."}` |
| 422 | 입력값 오류, 읽을 수 없는 GPX | FastAPI 검증 오류 형식, GPX는 이유 문장 |

## 계정

### `POST /auth/signup`

```json
{ "login_id": "dubu-mom", "password": "8자 이상", "name": "두부 보호자" }
```

아이디는 공백을 지우고 소문자로 바꾼 뒤, 3~30자의 영문 소문자, 숫자, `.`, `_`, `-`(영문이나 숫자로 시작)인지 확인합니다. 비밀번호는 8~128자입니다. 가입하면 바로 로그인 쿠키를 주고 `201`을 돌려줍니다. 같은 아이디가 있으면 `409`입니다. 새 계정은 반려동물 없이 기본 일정(16~20시)으로 시작합니다.

### `POST /auth/login` · `POST /auth/logout` · `GET /auth/me`

로그인은 `{ "login_id", "password" }`를 받아 쿠키를 줍니다. 틀리면 아이디가 없는지 비밀번호가 틀렸는지 구분하지 않고 `401`, 같은 아이디로 5번 연달아 틀리면 10분 동안 `429`입니다. 로그아웃은 서버의 세션을 지우고 쿠키를 지웁니다. 세 요청 모두 아래 형식을 돌려줍니다.

```json
{ "authenticated": true, "auth_required": false, "user": { "id": 2, "name": "두부 보호자", "login_id": "dubu-mom" } }
```

세션은 로그인한 지 30일이 지나거나 7일 동안 요청이 없으면 끝납니다. 끝난 세션으로 보낸 요청은 시연 보호자로 처리하지 않고 `401`과 쿠키 삭제로 응답합니다.

`/auth/me`는 만료된 쿠키를 지우고 로그인하지 않은 상태로 알려 줍니다. `google_enabled`는 서버에 Google 클라이언트가 설정되어 있는지입니다. `user.provider`는 `password` 또는 `google`이고, Google 사용자는 `login_id`가 `null`이며 Google이 확인한 이메일이 `email`에 들어갑니다.

### `GET /auth/google/start?next=/my-walks`

브라우저를 이 주소로 보내면(페이지 이동) Google 로그인 화면으로 `302` 리디렉션합니다. PKCE(S256), state, nonce를 붙이고, state를 `pawpath_google_state` 쿠키(HttpOnly, 10분, 경로 `/api/auth/google`)로도 줍니다. `next`는 로그인 뒤 돌아갈 앱 안의 경로이며 다른 사이트 주소면 `/`로 바꿉니다. Google 클라이언트가 설정되지 않았으면 `404`입니다.

`?reauth=true`를 붙이면 로그인이 아니라 지금 Google 보호자의 본인 재확인입니다. 끝나면 `/account`로 돌아옵니다. 로그인하지 않았으면 `/login`, 아이디 계정이면 `/account?error=google_mismatch`로 보냅니다.

### `GET /auth/google/callback`

Google이 돌려보내는 주소이며 콘솔의 리디렉션 URI와 같아야 합니다. 서버가 승인 코드를 클라이언트 비밀값과 PKCE 검증값으로 교환하고, ID 토큰의 발급자, 대상, 만료, nonce를 확인한 뒤 세션 쿠키를 주고 `next`로 `302` 리디렉션합니다. 같은 Google 계정(`sub`)은 늘 같은 보호자이고, 처음이면 보호자를 새로 만듭니다.

실패하면 `/login?error=이유`로 보냅니다.

본인 재확인이면 새 세션을 만들지 않습니다. 같은 Google 계정(`sub`)이고 시작한 세션이 그대로일 때만 지금 세션에 기록하고 토큰을 바꿉니다. 다른 계정이면 `/account?error=google_mismatch`로 보내고, 실패와 취소도 `/account?error=이유`로 알립니다.

| 이유 | 상황 |
|---|---|
| `google_cancelled` | Google 화면에서 사용자가 취소 |
| `google_state` | state가 없거나 브라우저 쿠키와 다름, 이미 썼거나 10분이 지남 |
| `google_failed` | 토큰 교환 실패, ID 토큰 확인 실패, Google의 다른 오류 |
| `google_unavailable` | 서버에 Google 클라이언트가 설정되지 않음 |
| `google_mismatch` | 본인 재확인에서 로그인한 계정과 다른 Google 계정을 고름 |

### `POST /auth/reauth`

```json
{ "password": "지금 비밀번호" }
```

비밀번호로 본인을 다시 확인합니다. 맞으면 세션 토큰을 바꾼 쿠키와 `{ "reauth_required": false }`를 줍니다. 세션의 남은 기간은 늘지 않습니다. 틀리면 `403`, 5번 연달아 틀리면 10분 동안 `429`입니다(로그인과 따로 세어 주인의 로그인은 막히지 않음). Google 계정은 `409`, 세션이 없으면 `401`입니다.

### `GET /auth/account`

탈퇴하면 지워질 데이터와 로그인 유지 기간입니다. 실제 세션이 있어야 하며 시연 보호자는 `401`입니다.

```json
{
  "provider": "password",
  "reauth_required": false,
  "session_expires_at": "2026-11-30T17:59:00",
  "session_idle_days": 7,
  "data": { "pets": 1, "walks": 2, "feedback": 1, "recommendations": 1, "saved_walks": 2, "photos": 1, "personal_courses": 1, "shared_walks": 2, "community_trails": 0, "trail_reviews": 0 },
  "backup_retention_days": 14
}
```

`reauth_required`가 참이면 탈퇴 전에 본인을 다시 확인해야 합니다. 로그인이나 재확인 뒤 10분 동안은 거짓입니다. `backup_retention_days`는 자동 백업을 쓰지 않으면 `null`입니다.

### `DELETE /auth/account`

계정과 데이터를 유예 기간 없이 지우고 `204`와 함께 쿠키를 지웁니다. 다른 기기의 세션도 끝나고, 공유 링크는 `404`가 되며, 아이디는 다시 쓸 수 있습니다. `Clear-Site-Data: "cache"`로 이 브라우저의 사진 캐시도 지웁니다.

본인 재확인이 안 되었으면 `403`, 탈퇴 기록을 남기지 못하면 아무것도 지우지 않고 `503`입니다.

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

로그인 없이 열리며, 공용 코스와 보는 사람의 내 산책길 코스(`is_personal: true`)를 돌려줍니다. 다른 보호자의 내 산책길 코스는 번호로 조회해도 `404`입니다. 출발점 길찾기, 주변 시설, 안전 평가, 산책 기록, 대체 경로도 같은 기준으로 막습니다. 내 산책길 코스의 `data_sources.unknown`에는 측정도 추정도 없어 "확인 불가"로 다루는 속성이 들어갑니다.

코스 정보, 경로(`route`: `[위도, 경도]` 배열), 시설(`facilities`), 출처(`data_sources`)를 돌려줍니다. 목록은 서버 설정 `SERVICE_AREA` 지역의 코스만 돌려주고, 번호로 조회하면 지역과 관계없이 돌려줍니다.

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

### `POST /routes/generate`

출발 위치와 원하는 산책 시간으로 한 바퀴 도는 경로 후보를 만듭니다. 로그인이 필요합니다. 공용 도보 길찾기 서버를 여러 번 불러 **보통 약 10초, 후보가 모자라는 곳에서는 거리 보정까지 하느라 최대 30초 남짓** 걸립니다. 위치는 계산에만 쓰고 저장하지 않습니다.

```json
{ "latitude": 37.5559, "longitude": 126.9105, "duration_min": 30, "pet_id": 1, "weather_scenario": "live" }
```

`duration_min`은 20~90입니다(걷는 속도 60m/분). `pet_id`는 선택이며, 주면 후보를 그 반려동물의 성향·날씨·일정·지난 피드백으로 평가해 맞는 순서로 돌려줍니다. 응답:

```json
{
  "target_min": 30,
  "candidates": [
    {
      "route": [[37.5559, 126.9105], "..."], "distance_m": 1840.2, "duration_min": 30.7, "repeated_pct": 4.1, "start_snap_m": 1.0,
      "fit": {
        "score": 78.4, "level": "good", "summary": "두부에게는 ...", "details": ["..."], "cautions": [],
        "highlights": ["공원을 지나는 길이 약 32%", "큰 도로변 비율 약 0%", "가까이 있는 시설: 화장실 2곳"],
        "start_label": "오후 4시", "unknown": [], "excluded": []
      }
    }
  ],
  "notice": null,
  "scored_for": "두부",
  "fit_notice": null
}
```

- `fit`은 `pet_id`를 줬을 때만 있고(없으면 `null`, `scored_for`도 `null`), 후보 순서가 곧 맞는 순서입니다. 점수는 저장한 코스를 추천할 때와 같은 엔진(`/recommendations`)으로 계산하므로 반려동물 성향·날씨·일정·지난 피드백이 같은 기준으로 들어갑니다. 시간 오차, 되돌아오는 구간 같은 기준은 먼저 후보를 거르는 데 쓰고, 그 뒤 엔진이 시간·거리 적합도를 포함해 점수를 매깁니다.
- 주변 환경(도로 종류, 조명, 노면, 나무, 공원)은 **미리 수집해 둔 서비스 지역(망원동·개포동 주변 약 6km 상자)의 OpenStreetMap 자료**로 측정합니다. 자료가 덮지 않는 곳이거나 OSM에 태그가 없는 항목은 `unknown`에 이름이 담기고 중립값으로 계산하되 안전하다고 보지 않습니다. `highlights`는 측정한 사실만 담습니다.
- `excluded`가 비어 있지 않은 후보는 추천 엔진이 이 시간대에는 권하지 않은 경로입니다(점수 없음, 순서는 뒤). 모든 후보가 그렇다면 `fit_notice`에 이유가 담깁니다.

- 후보는 최대 5개이며 목표 시간에 가깝고 서로 덜 겹치는 순입니다. 목표 시간보다 20% 넘게 짧거나 50% 넘게 긴 경로, 같은 길을 다시 지나는 비율이 25%를 넘는 경로, 출발·경유 지점이 가장 가까운 길에서 150m 넘게 떨어진 경로는 내놓지 않습니다. 출발 위치가 공원이나 단지 안이면 `start_snap_m`만큼 떨어진 가까운 길에서 경로가 시작합니다. 기준에 맞는 경로가 없으면 `candidates`가 비고 `notice`에 이유가 담깁니다(200).
- 경사와 반려견 출입 여부는 평가하지 않습니다. 20분과 90분 조건은 실측하지 않았습니다.
- 마음에 드는 후보는 `POST /my-walks`에 `source_type: "generated"`로 저장하고, 이어서 `POST /my-walks/{id}/course`로 추천 후보에 넣습니다.
- `429`: 다른 경로를 만드는 중이거나 이 계정이 방금 만들었습니다. `Retry-After` 초 뒤에 다시 시도합니다. `502`: 길찾기 서버에서 경로를 받지 못했습니다. `503`: 길찾기를 사용하지 않도록 설정되어 있습니다.
- 기본 설정에서는 8방향(45° 간격)을 항상 모두 시도한 뒤 좋은 후보를 고릅니다. 5개가 모이지 않으면 시간 오차가 큰 후보의 거리 보정(최대 3회)을 더해, 한 번에 8~11회 공용 서버를 호출합니다. 전체 제한 시간은 30초입니다. 방위 수, 경유점 거리·각도 조합, 요청 상한, 돌려주는 후보 수는 `GENERATION_*` 설정으로 바꿀 수 있습니다(자체 서버용, README 참고).
- 한 프로세스에서 한 번에 한 건만 처리하고 계정마다 완료 뒤 10초를 쉽니다. 서버 워커가 여러 개면 이 제한은 워커마다 따로 적용됩니다.

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

`recommendation_id`, `started_at`은 선택입니다. `started_at`이 없으면 지금 끝난 산책으로 기록합니다. 코스 방문 수가 함께 올라갑니다. `started_at`은 시간대 학습에 쓰이므로 나중에 기록할 때는 실제 출발 시각을 보냅니다. 타임존이 붙어 있으면 서비스 현지 시각으로 바꾸고, 끝나는 시각(`started_at` + `duration_min`)이 지금보다 30분 넘게 늦으면 422로 거부합니다. 30분은 휴대폰과 서버 시계 차이를 위한 여유입니다.

선택 필드: `tracking_source`(`gps`, `manual`, `simulation`, 기본 `manual`), `distance_km`(실제 걸은 거리, 없으면 코스 거리). `simulation`은 활동 통계에서 제외합니다.

### `GET /walks?pet_id=1`

최신순 산책 기록과 각 산책의 피드백입니다. `tracking_source`, `is_simulated`를 함께 돌려줍니다.

### `DELETE /walks/{walk_id}`

잘못 남긴 산책 기록을 지웁니다(204). 기록할 때 올린 코스 방문 수를 되돌립니다. 피드백을 남긴 산책은 이미 학습에 반영되어 409로 거부합니다. 남의 기록이면 404입니다.

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

## 나만의 산책길

직접 기록하거나 GPX로 가져온 산책길입니다. 추천 코스의 `/walks`와 별개이며 추천 학습에는 쓰지 않습니다.

### `POST /my-walks`

```json
{
  "title": "새롬관 옆 양재천 산책",
  "pet_id": 1,
  "memo": "",
  "visibility": "private",
  "share_memo": false,
  "source_type": "recorded",
  "client_id": "rec-2f6c0a6e-1b7e-4f0a-9d7a-5d1c2b3a4e5f",
  "duration_sec": 1260,
  "points": [
    { "latitude": 37.4895, "longitude": 127.0664, "altitude": null, "accuracy": 6, "recorded_at": "2026-10-31T16:00:00", "segment": 0 }
  ]
}
```

- `points`는 2개 이상 10만 개 이하이고 순서대로 저장합니다. `segment`가 바뀌는 곳(일시정지, GPX `trkseg`)은 선을 잇지 않고 거리에 넣지 않습니다.
- `visibility`: `private`(기본), `link`, `public`. `private`가 아니면 공유 토큰을 함께 만듭니다.
- `source_type`: `recorded`(직접 기록), `imported`(GPX), `generated`(`/routes/generate`로 만든 경로. 시각이 없고 서버가 출처를 검증하지 않는 값입니다). 기록은 같은 좌표가 이어진 지점을 빼고, `duration_sec`(일시정지를 뺀 시간)을 씁니다. GPX는 시각으로 시간을 계산하고, 시각이 없으면 `null`입니다.
- 거리, 평균 속도, 시작과 끝 시각은 서버가 좌표로 다시 계산합니다. 100m 넘게 움직이면서 시속 252km(초속 70m)를 넘는 이동, 시각이 없거나 같으면 5km를 넘는 간격은 구간을 나눠 거리에서 뺍니다.
- `client_id`가 같은 요청을 다시 보내면 새로 만들지 않고 저장된 산책길을 `200`으로 돌려줍니다. 처음 저장하면 `201`입니다.

### `GET /my-walks?sort=recent&pet_id=1&visibility=link`

목록입니다. `sort`는 `recent`(기본) 또는 `distance`, `pet_id`와 `visibility`는 선택입니다. 각 항목은 전체 좌표 대신 약 80개로 줄인 `preview` 경로를 담습니다.

### `GET /my-walks/{walk_id}` · `PATCH /my-walks/{walk_id}` · `DELETE /my-walks/{walk_id}`

상세에는 `route`(구간별 전체 경로), `memo`, `share_token`, `share_expires_at`이 더해집니다. `PATCH`는 보낸 항목만 바꾸며 `title`, `pet_id`, `memo`, `visibility`, `share_memo`를 받습니다. `pet_id`만 `null`로 비울 수 있습니다. 비공개로 바꾸면 공유 토큰을 지웁니다. `DELETE`는 지점까지 함께 지우고 `204`를 돌려줍니다.

### `GET /my-walks/{walk_id}/gpx`

GPX 1.1 파일(`application/gpx+xml`, UTF-8)입니다. 구간, 시각(UTC), 고도를 담습니다. `Content-Disposition`에 한글 이름(`filename*`)과 영문 대체 이름(`filename`)을 함께 줍니다.

### `POST /my-walks/import/preview`

GPX 파일 원본을 요청 본문으로 보냅니다(`Content-Type: application/gpx+xml`). 저장하지 않고 검증 결과와 미리보기를 돌려줍니다.

| 필드 | 내용 |
|---|---|
| `name`, `version` | 파일의 이름과 GPX 버전 |
| `track_count`, `segment_count`, `point_count`, `invalid_point_count` | 트랙, 구간, 지점 수와 버린 좌표 수 |
| `has_timestamps`, `distance_m`, `duration_sec`, `average_speed_mps` | 시각 유무와 계산 결과 |
| `warnings` | 버린 좌표, 시각 없음, 여러 트랙, 순서가 뒤바뀐 시각, 순간 이동 |
| `duplicate_of` | 같은 경로가 이미 있으면 `{id, title}` |
| `points` | 파일 순서 그대로의 지점. 이 값을 `POST /my-walks`에 `source_type: "imported"`로 보내 저장 |

10MB를 넘으면 `413`, 빈 파일, XML 오류, GPX가 아닌 파일, 지원하지 않는 버전, 좌표가 없는 파일, DOCTYPE과 엔티티 선언이 있는 파일은 이유와 함께 `422`입니다.

### `POST /my-walks/{walk_id}/photos` · `GET /my-walks/{walk_id}/photos/{photo_id}` · `DELETE /my-walks/{walk_id}/photos/{photo_id}`

사진 원본을 요청 본문으로 보냅니다. 형식은 `Content-Type`이 아니라 파일 내용으로 판단하며 JPG와 PNG만 받습니다. JPEG는 EXIF(촬영 위치), XMP, IPTC, 주석과 끝 표시 뒤에 붙은 보조 이미지를, PNG는 `eXIf`, `tEXt`, `zTXt`, `iTXt`, `tIME` 조각을 지우고 저장합니다. 산책길마다 5장, 장당 5MB까지이며 넘으면 `409`, `413`입니다. 손상된 파일은 `422`입니다.

`GET`은 사진 파일을 `Cache-Control: private`, `X-Content-Type-Options: nosniff`와 함께 돌려줍니다. 상세 응답의 `photos`에는 `id`, `content_type`, `size_bytes`, `created_at`만 담습니다. 사진은 공유 응답과 공개 목록에 나오지 않습니다.

### `POST /my-walks/{walk_id}/course` · `DELETE /my-walks/{walk_id}/course`

산책길을 내 추천 후보 코스로 등록하거나 뺍니다. 응답은 산책길 상세이며 `course`에 상태가 들어갑니다.

```json
{ "id": 17, "active": true, "area": "서울 마포구 망원동 일대", "in_current_area": true, "environment_measured": false, "measurement": "pending", "unknown": ["crowd_level", "difficulty", "has_park", "is_paved", "shade_level", "traffic_exposure"], "notes": ["주변 도로, 조명, 노면, 나무, 공원을 OpenStreetMap에서 측정하고 있어요. ..."] }
```

- 등록은 바로 응답하고, 주변 환경은 응답을 보낸 뒤 Overpass로 측정합니다. `measurement`는 `pending`(측정 중), `done`, `failed`, `off`(`ENVIRONMENT_PROVIDER=none`)이고, 5분이 지나도 끝나지 않으면 `failed`로 봅니다. 다시 `POST`하면 다시 측정합니다.
- 서비스 지역 5km 밖, 0.1km 미만 또는 10km 초과, 구간 사이가 100m 넘게 떨어진 산책길은 이유와 함께 `422`입니다.
- `DELETE`는 추천 후보에서만 빼고, 이 코스로 남긴 산책 기록과 피드백은 그대로 둡니다. 산책길을 지워도 코스는 추천에서만 빠집니다.

### `POST /my-walks/{walk_id}/share` · `DELETE /my-walks/{walk_id}/share`

```json
{ "expires_in_days": 7, "share_memo": false }
```

공유 링크를 만듭니다. 비공개면 `link`로 바꾸고 32자 무작위 토큰을 만듭니다. `expires_in_days`는 1~365일이며 비우면 기간이 없습니다. 공개 산책길은 기간을 두지 않습니다. 기간이 끝난 뒤 다시 만들면 새 토큰을 씁니다. `DELETE`는 공유를 해제하고 비공개로 돌립니다.

## 공유

로그인 없이 누구나 호출할 수 있습니다(`AUTH_REQUIRED=true`여도 열림). 비공개 산책길과 해제된 링크는 없는 링크와 같은 `404`, 기간이 끝난 링크는 `410`입니다.

### `GET /shared/{token}`

```json
{ "title": "새롬관 옆 양재천 산책", "distance_m": 1350.4, "duration_sec": 1260, "memo": null, "start": [37.4895, 127.0664], "end": [37.4901, 127.0672], "route": [[[37.4895, 127.0664], [37.4898, 127.0667]]] }
```

걸은 시각, GPS 정확도, 반려동물, 보호자 정보는 담지 않습니다. `memo`는 `share_memo`가 켜져 있을 때만 들어갑니다.

### `GET /shared/{token}/gpx`

공유용 GPX입니다. 언제 걸었는지 드러나지 않도록 시각과 고도를 빼고, 파일 이름에도 날짜를 넣지 않습니다.

### `GET /public-walks`

공개로 설정한 산책길 목록입니다. 각 항목은 `token`, `title`, `distance_m`, `duration_sec`, `preview`만 담습니다.

## 산책길 커뮤니티

내 산책길을 공개하고 둘러보는 API입니다. `GET`과 `/view`, `/start`, `/nearby`는 로그인 없이 부를 수 있고, 나머지는 실제 로그인이 필요합니다. 시연 보호자로는 쓸 수 없어 `AUTH_REQUIRED=false`여도 `401`입니다. 다른 보호자의 비공개 산책길은 없는 산책길과 같은 `404`이고, 공개 산책길을 주인이 아닌 사람이 고치면 `403`입니다.

공개 값에는 출발점과 도착점 반경 안의 지점이 없고, 원본 산책길의 이름, 메모, 걸은 시각, 공유 토큰, 반려동물, 가리는 반경이 들어가지 않습니다. 작성자는 이름(`author_name`)만 보냅니다.

### `POST /community/trails/preview`

```json
{ "saved_walk_id": 12, "hide_radius_m": 200 }
```

공개될 경로와 계산 값을 미리 돌려줍니다. 저장하지 않습니다. 응답은 `route`, `distance_m`, `estimated_min`, `elevation_gain_m`, `difficulty`, `region`(추천 지역), `start_label`, `end_label`, `hidden_m`, `can_navigate`입니다. 가린 뒤 100m보다 짧게 남으면 `422`입니다.

### `POST /community/trails`

```json
{
  "saved_walk_id": 12,
  "title": "망원 한강공원 저녁 산책길",
  "description": "해 질 때 걷기 좋아요",
  "cover_photo_id": 3,
  "visibility": "public",
  "region": "",
  "features": ["park", "waterside"],
  "suitable_for": ["small", "senior"],
  "hide_radius_m": 200
}
```

- `saved_walk_id`만 내 산책길을 가리키면 되고 좌표는 보내지 않습니다. 남의 산책길이면 `404`입니다.
- `title` 1~80자, `description` 2000자까지. 제어 문자는 지웁니다.
- `visibility`: `public`(기본), `private`. `hide_radius_m`: `100`, `200`(기본), `300`, `500`.
- `features`: `park`, `shade`, `flat`, `paved`, `waterside`, `forest`, `quiet`, `lit`. `suitable_for`: `small`, `medium`, `large`, `senior`, `puppy`, `active`, `timid`.
- `region`을 비우면 출발점 5km 안의 서비스 지역 이름, 없으면 `기타 지역`을 씁니다. 주소 검색 API는 위치를 외부로 보내게 되어 쓰지 않습니다.
- `cover_photo_id`는 이 산책길의 사진만 고를 수 있고(`422`), 고른 한 장만 공개됩니다.
- 이미 공유한 산책길이나 같은 경로면 `409`입니다.
- 직접 기록(`recorded`)과 GPX(`imported`)만 공유합니다. 자동 생성 경로(`generated`)는 미리보기와 공유 모두 `422`입니다.

### `GET /community/trails`

`q`(이름, 지역, 설명), `region`, `min_km`, `max_km`, `min_minutes`, `max_minutes`, `difficulty`(`easy`, `moderate`, `hard`), `suitable`, `feature`, `sort`(`recent`, `popular`, `rating`), `page`, `size`(최대 50, 기본 12).

```json
{ "items": [{ "id": 1, "title": "...", "region": "...", "author_name": "앨리스", "distance_m": 2998.4, "estimated_min": 39, "elevation_gain_m": 23.0, "difficulty": "moderate", "preview": [[[37.55, 126.91]]], "cover_photo_id": 3, "view_count": 12, "like_count": 4, "bookmark_count": 2, "review_count": 1, "average_rating": 5.0, "liked": false, "bookmarked": false, "is_mine": false, "visibility": "public", "features": [], "suitable_for": [], "description": "", "created_at": "...", "updated_at": "..." }], "total": 1, "page": 1, "size": 12, "has_next": false }
```

좋아요 수와 평점은 저장하지 않고 읽을 때 집계합니다. 인기순은 `좋아요×3 + 저장×2 + 후기×2 + 조회×0.1`, 평점순은 후기 3개 분량의 3.5점을 섞은 평균입니다. 후기가 하나뿐인 5점이 후기가 많은 높은 평균을 앞서지 않게 하기 위해서입니다. 난이도는 5km 이상이나 오르막 100m 이상이면 `hard`, 2km 이상이나 30m 이상이면 `moderate`입니다. 고도 기록이 절반이 안 되면 `elevation_gain_m`이 `null`이고 거리로만 정합니다.

### `POST /community/trails/nearby`

```json
{ "latitude": 37.55, "longitude": 126.91, "radius_km": 5, "limit": 20 }
```

위치가 접근 로그에 남지 않도록 본문으로 받고 저장하지 않습니다. 각 항목에 `distance_from_me_m`(10m 단위)가 더해집니다.

### `GET /community/trails/recommended?pet_id=1&limit=6`

내 반려동물에게 맞는 순서입니다. 내가 공유한 길은 뺍니다. 각 항목에 `match_score`(0~100)와 `reasons`가 더해집니다. 점수는 권장 거리 35%, 추천 대상 20%, 평점 20%, 학습된 취향 15%, 지형 10%입니다. 남의 반려동물이면 `404`입니다.

### `GET /community/regions`

공개 산책길이 있는 지역과 개수입니다. `[{ "region": "서울 마포구 망원동 일대", "count": 3 }]`

### `GET /community/trails/{id}` · `PATCH /community/trails/{id}` · `DELETE /community/trails/{id}`

상세에는 `route`(가린 경로), `start`, `end`, `start_label`, `end_label`(가까운 공원 이름, 없으면 `null`), `can_navigate`, `my_review`, `walked`(보는 사람이 GPS로 걸은 기록 여부), `owner`(주인에게만 `saved_walk_id`, `hide_radius_m`)가 더해집니다. `PATCH`는 만든 때와 같은 항목에서 보낸 것만 바꾸며, `cover_photo_id`만 `null`로 비울 수 있습니다. `hide_radius_m`을 바꾸면 공개 값과 길 안내 코스를 다시 계산합니다. `DELETE`는 공유 해제입니다. 좋아요, 저장, 후기를 함께 지우고 원본 산책길은 남깁니다(`204`).

### `POST /community/trails/{id}/view`

조회수를 올립니다(`204`). 화면이 세션마다 한 번 부르고, 주인은 세지 않습니다. 상세를 읽는 것만으로는 올라가지 않습니다.

### `GET /community/trails/{id}/gpx`

공개용 GPX입니다. 가린 경로만 담고 시각, 고도, 원본 이름, 메모, 작성자를 넣지 않으며 파일 이름에도 날짜가 없습니다.

### `GET /community/trails/{id}/cover`

대표 이미지입니다. `Cache-Control: private, max-age=300`, `X-Content-Type-Options: nosniff`와 함께 돌려줍니다. 없으면 `404`입니다.

### `POST /community/trails/{id}/start`

이 산책길의 길 안내 코스 번호를 돌려줍니다. `{ "course_id": 21 }`. 산책길마다 하나만 만들어 함께 쓰며 추천 후보에는 넣지 않습니다. `/courses/{id}`, `/walks`, `/feedback`을 기존과 같이 쓸 수 있고, `/walks` 응답의 `community_trail_id`로 후기에 이을 수 있습니다. 산책길이 비공개가 되면 코스도 주인에게만 열리고, 공유를 해제하면 경로를 지워 `404`가 됩니다. 가린 구간이나 끊긴 구간이 100m를 넘어 한 줄로 이을 수 없으면 `422`입니다.

### `POST /community/trails/{id}/like` · `DELETE` · `POST /community/trails/{id}/bookmark` · `DELETE`

`{ "liked": true, "like_count": 4 }`, `{ "bookmarked": true, "bookmark_count": 2 }`. 여러 번 보내도 결과가 같고, DB 고유 제약이 동시 요청의 중복도 막습니다.

### `GET /community/trails/{id}/reviews` · `POST /community/trails/{id}/reviews`

```json
{ "rating": 5, "content": "직접 걸어 보니 좋았어요" }
```

`rating` 1~5, `content` 1~1000자입니다. 산책길마다 한 번만 쓰며 두 번째는 `409`, 내 산책길이면 `403`입니다. 응답의 `verified`는 이 산책길의 코스를 `tracking_source: "gps"`로 절반 이상 걸은 기록이 있을 때 참이며, 읽을 때 계산하므로 나중에 걸으면 붙고 기록을 지우면 떨어집니다. 시연용 걷기와 직접 입력은 세지 않습니다.

### `PATCH /community/reviews/{id}` · `DELETE /community/reviews/{id}`

내 후기만 고치거나 지웁니다. 남의 후기면 `403`입니다.

### `POST /community/reviews/{id}/photos` · `GET /community/reviews/{id}/photos/{photo_id}` · `DELETE ...`

산책길 사진과 같은 검사를 거칩니다(JPG, PNG, 5MB, 메타데이터 제거). 후기마다 3장이며 넘으면 `409`입니다. 산책길을 볼 수 없으면 사진도 `404`입니다.

### `GET /community/my/trails` · `/my/bookmarks` · `/my/likes` · `/my/reviews`

내 활동입니다. `bookmarks`와 `likes`는 작성자가 비공개로 돌린 길을 빼고 `hidden_count`로 개수만 알려 줍니다. `reviews`의 각 항목에는 `trail_available`, `trail_title`이 더해지고, 볼 수 없는 길이면 이름이 `null`입니다.

## 시스템

### `GET /health`

`{"status": "ok", "service": "PawPath"}`
