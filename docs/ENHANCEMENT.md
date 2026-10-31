# PawPath 고도화 보고서

기존 구조를 유지하면서 추천 정확도, 산책 안전성, 사용자 경험을 확장한 내용입니다. 각 기능의 실제 구현 여부를 구분해 적었습니다.

## 1. 기존 프로젝트 분석

| 항목 | 내용 |
|---|---|
| 구조 | `backend/`(FastAPI, SQLAlchemy), `frontend/`(React, Vite, Tailwind, Leaflet), `scripts/`, `docs/` |
| API | 반려동물, 일정, 날씨, 코스, 추천, 산책, 피드백, 분석 20개 |
| DB | `users`, `pets`, `walking_courses`, `weather_records`, `recommendations`, `walk_histories`, `walk_feedbacks`, `pet_course_preferences` |
| 추천 엔진 | `backend/app/recommender`: 특성값, 시간대 점수, 코스 6개 항목 가중합, 온라인 학습, 템플릿 설명 |
| 지도와 GPS | Leaflet + OSM 타일, `watchPosition`, 경로 추적, 이탈 판정, OSRM 도보 길찾기 |
| 외부 서비스 | Open-Meteo, OSM 타일, OSRM (Overpass는 데이터 구축 때만) |
| LLM | 저장소에 연동 코드 없음. 개발 PC에 로컬 Ollama 실행 중 |

## 2. 기존 기능과 개선 비교

| 요구 | 이전 | 이후 | 상태 |
|---|---|---|---|
| 점수 모델 | 6개 항목, 가중치 코드 고정 | 지시서의 6개 평가 묶음으로 응답, `RECOMMENDER_WEIGHTS`로 설정 | 구현 |
| 선호 거리, 선호 시간 | 없음 | 프로필 선택 입력, 사용자 선호도 항목에 반영 | 구현 |
| 코스 선택 이력 | 익숙함 계산에만 사용 | 사용자 선호도에도 반영, 낮게 평가한 코스 제외 | 구현 |
| 신규 사용자 | 중립값 처리 | 규칙 기반 모드로 명시 | 구현 |
| 개인화 가중치 조정 | 과거 선호도 강도 조정 | 유지. 코스 특성 가중치와 시간대 선호를 반려동물별 학습 | 구현 |
| 학습 모델 교체 구조 | 없음 | `Ranker` 인터페이스 분리 | 구조만 구현. LightGBM은 미적용 |
| 안전 평가 | 시간대 제외만 있음 | 11개 항목 평가, 코스 단위 제외와 감점, 위험 요인 설명 | 구현 |
| 데이터 출처 구분 | 추정 표시 일부 | 예보, OSM 기록, 팀 추정, 모의, 확인 불가 | 구현 |
| 대체 코스 | 없음 | 위험 수준이 실제로 낮은 코스 제시 | 구현 |
| LLM 추천 이유 | 없음 | Ollama 연동, 사실 검증, 실패 시 템플릿 | 구현 |
| 산책 중 재평가 | 없음 | 5분 간격 및 버튼으로 재평가, 복귀 경로, 대체 코스 | 구현 (예보 기반) |
| 경로 재탐색 | 직선 점선만 | 이탈 시 도보 경로 재탐색 (30초 제한), 실패 시 직선 | 구현 |
| 주변 시설 | 경로 60m 이내 일부 | 8종, 300m 검색, 출처와 한계 표시 | 구현 |
| 주간 리포트 | 누적 분석만 | 주간 요약, 일별 기록, 만족도 변화, 지난주 대비, 추천 비교 | 구현 |
| 시연 데이터 분리 | 통계에 섞임 | 활동 통계에서 제외, 건수만 별도 표시 | 구현 |

## 3. 변경 파일

**신규 (백엔드):** `recommender/config.py`, `recommender/safety.py`, `recommender/explain_guard.py`, `recommender/text.py`, `services/llm_service.py`, `services/alternative_service.py`, `services/report_service.py`, `services/places_service.py`, `migrations.py`, `data/places.json`, `tests/test_safety.py`, `tests/test_llm.py`, `tests/test_enhancement.py`, `tests/test_scenarios.py`

**신규 (프론트엔드):** `pages/ReportPage.tsx`, `components/SafetyPanel.tsx`, `components/NearbyPlaces.tsx`, `components/charts/DailyColumns.tsx`, `components/charts/RatingLine.tsx`

**신규 (기타):** `scripts/enrich_courses.py`, `docs/ENHANCEMENT.md`, `docs/VALIDATION.md`

**수정:** `recommender/`의 `types`, `features`, `timeslots`, `preference`, `course_scoring`, `engine`, `explain`; `services/`의 `recommendation_service`, `walk_service`, `weather_providers`, `weather_service`; `api.py`, `models.py`, `schemas.py`, `config.py`, `main.py`; `data/courses.json`; 프론트엔드 `NavigatePage`, `RecommendPage`, `MapPage`, `MyPage`, `WalkPage`, `PetFormPage`, `HomePage`, `NavigationMap`, `CourseMap`, `AppContext`, `lib/`; E2E 테스트; README와 문서

## 4. 개선된 추천 알고리즘

```
최종 점수 = 날씨 × 25% + 성향 × 25% + 활동량 × 15% + 일정 × 15% + 안전 × 10% + 10% × 50
          + g × (과거 만족도 − 50)
          + 10% × (사용자 선호도 − 50)
          − 위험 감점

g = 10% + 20% × 피드백 수 / (피드백 수 + 2)
```

응답의 6개 평가 묶음과의 관계는 다음과 같습니다.

| 평가 묶음 | 세부 항목 | 입력 데이터 |
|---|---|---|
| 반려동물 적합도 | 성향, 활동량 | 나이, 크기, 체중, 활동량, 성격, 낯선 환경 반응 |
| 사용자 선호도 | 사용자 선호도 | 선호 거리, 선호 시간대, 코스 선택 이력 |
| 날씨 적합도 | 날씨 | 체감온도, 강수, 바람, 자외선, 그늘 |
| 산책 안전성 | 안전 | 안전 지수 |
| 시간 적합도 | 일정 | 희망 시간, 가능 시간대 |
| 과거 만족도 | 과거 선호도 | 피드백 학습 |

- 사용자 선호도와 과거 만족도는 중립값에서 벗어난 만큼만 반영합니다. 입력과 피드백이 없으면 점수는 이전과 같습니다.
- 가중치는 `RECOMMENDER_WEIGHTS`로 바꿉니다. 예: `{"weather": 0.3, "safety": 0.2}`. 기본 항목은 합이 1이 되도록 맞추고, 잘못된 값은 기본값으로 돌아갑니다.
- 순위 계산은 `recommender/config.py`의 `Ranker`로 분리했습니다. 산책 데이터가 쌓이면 항목 점수와 피드백으로 학습한 모델을 같은 자리에 넣을 수 있습니다. 데이터가 없는 지금은 머신러닝을 쓰지 않습니다.

## 5. 안전 지수

`recommender/safety.py`가 항목별 상태(양호, 주의, 위험, 확인 불가)와 출처를 평가합니다.

| 항목 | 데이터 | 출처 |
|---|---|---|
| 기온, 강수, 바람, 자외선 | Open-Meteo | 예보 (시나리오면 모의) |
| 시간대 | 예보의 낮밤 정보 | 예보 |
| 조명 | OSM `lit` 태그. 경로의 50% 이상 기록이 있을 때만 사용 | OSM 기록, 없으면 확인 불가(팀 추정 병기) |
| 그늘 | OSM 나무 기록 근접 비율. 기록이 없으면 사실로 쓰지 않음 | OSM 기록, 없으면 확인 불가(팀 추정 병기) |
| 차량 노출 | OSM 도로 등급 비율 | OSM 기록 |
| 노면 | OSM `surface` 태그 | OSM 기록, 없으면 확인 불가(팀 추정 병기) |
| 주변 시설, 공원 | OSM | OSM 기록 |

**점수:** 항목 점수의 가중 평균입니다. 낮에는 차량 노출과 날씨, 해가 진 뒤에는 조명 비중이 커집니다. 데이터가 없는 항목은 40점으로 계산해 안전하다고 보지 않습니다.

**추천 제외 (대체 코스 추천):**

- 시간대: 강한 비, 제외 체감온도, 강풍 (기존)
- 비가 오는 시간의 비포장 코스
- 쾌적 상한 +6°C 이상에서 30분을 넘는 산책 중 그늘을 확인할 수 없는 코스
- 해가 진 뒤 조명이 부족한 코스 (겁이 많거나 나이 든 경우)
- 초속 10m 이상 바람의 강변 코스

**감점:** 주의 항목당 1.5점, 위험 항목당 5점, 최대 15점.

안전 점수는 환경 위험을 비교하는 참고값이며 의학적, 절대적 안전을 보장하지 않습니다. 화면에도 표시합니다.

## 6. LLM 추천 이유

1. 추천 엔진이 순위와 점수를 확정해 저장합니다.
2. 화면은 템플릿 문장을 먼저 보여 줍니다.
3. `POST /recommendations/{id}/explain`이 근거 자료(점수 제외)를 LLM에 보냅니다.
4. 돌아온 문장을 `explain_guard.py`가 검증합니다: 이름 포함, 길이, 단정 표현, 위치 표현, 확인 불가 항목, 근거 없는 시설과 숫자.
5. 통과한 문장만 `reason.llm_summary`에 저장합니다. 나머지는 템플릿을 씁니다.

LLM은 문장 필드 말고는 아무것도 바꿀 수 없습니다. 기본값은 꺼짐(`LLM_PROVIDER=none`)이며 API 키 없이 동작합니다.

## 7. API 추가와 호환

모두 기존 경로와 충돌하지 않으며, 기존 응답 필드는 그대로 두고 추가만 했습니다. 상세는 [API 명세](API.md)에 있습니다.

| API | 용도 |
|---|---|
| `GET /api/safety` | 현재 환경 또는 코스의 안전 평가 |
| `POST /api/routes/alternative` | 산책 중 재평가, 복귀 경로, 대체 코스 |
| `POST /api/routes/walking` | 경로 재탐색 |
| `GET /api/walks/report` | 주간 활동 리포트 |
| `GET /api/courses/{id}/nearby` | 코스 주변 시설 |
| `POST /api/recommendations/{id}/explain` | LLM 문장 보강 |

`POST /api/recommendations`, `GET /api/recommendations/{id}`, `POST /api/feedback`, `POST /api/walks`는 기존 경로를 유지합니다.

**의도적으로 달라진 점:**

- 응답의 `factors`가 7개(사용자 선호도 추가), `weights`에 `user_preference` 추가
- 안전 점수 계산이 바뀌어 같은 입력이어도 총점이 이전과 다를 수 있음
- 동네숲 코스의 `has_park`가 거짓으로, 차량 노출이 실측값으로 바뀜

## 8. DB 변경

새 테이블은 만들지 않았습니다. 지시서의 예시 테이블은 기존 테이블로 충분합니다.

| 예시 | 사용한 곳 |
|---|---|
| `pet_profiles` | `pets` |
| `walking_history` | `walk_histories` |
| `walking_feedback` | `walk_feedbacks` |
| `recommendation_results` | `recommendations.payload` |
| `route_safety_scores` | `recommendations.payload`, `walking_courses.environment` |

| 추가 컬럼 (모두 비어 있어도 됨) | 용도 |
|---|---|
| `pets.preferred_distance_km`, `pets.preferred_time_bucket` | 선호 거리, 시간대 |
| `walking_courses.environment` | OSM 측정값 |
| `walk_histories.tracking_source` | `gps`, `manual`, `simulation` |
| `walk_histories.distance_km` | 실제 걸은 거리 |

서버 시작 때 `migrations.py`가 빠진 컬럼을 자동으로 추가하므로 기존 DB를 그대로 쓸 수 있습니다.

## 9. 미구현 기능과 한계

| 항목 | 상태 |
|---|---|
| LightGBM 등 학습 순위 모델 | 미구현. 데이터가 없어 인터페이스만 분리 |
| 실시간 강수 감지 | 미구현. 시간별 예보로 판단하며 화면에 밝힘 |
| 안전한 복귀 지점 탐색 | 미구현. 복귀 목적지는 코스 출발점 |
| 지도 위 대체 코스 동시 표시 | 미구현. 목록에서 고르면 그 코스 안내로 전환 |
| Claude 등 클라우드 LLM | 미구현. 로컬 Ollama만 지원하며 `LlmProvider`로 추가 가능 |
| 가로등, CCTV 공공데이터 | 미연동. 망원동 OSM에 가로등과 CCTV 기록이 없어 조명은 대부분 확인 불가 |
| 나무, 그늘 데이터 | 기록이 적어 대부분 확인 불가. 나무 기록은 실제 그늘과 다를 수 있음 |
| 반려동물 동반 가능 여부 | OSM 표시만 보여 주며 확정하지 않음. 코스별 동반 여부는 팀 입력값 |
| 혼잡도 | 실측 없이 팀 추정값. 시간대별 변화 미반영 |
| 복수 사용자, 로그인 | 이후 작업에서 구현. 선택이며 `AUTH_REQUIRED=true`로 필수 ([README](../README.md#로그인-선택)) |
| 시연용 산책의 학습 | 활동 통계에서는 빼지만 피드백 학습에는 반영됨 |

## 10. 향후 고도화 방향

1. **조명, 혼잡 데이터 연동:** 서울시 가로등과 CCTV 공공데이터, 시간대별 유동인구
2. **학습 순위 모델:** 피드백이 충분히 쌓이면 항목 점수를 입력으로 하는 LightGBM Ranker 적용
3. **초단기 강수:** 기상청 초단기예보나 레이더로 산책 중 판단 정밀화
4. **복귀 지점 다양화:** 가까운 지하철역, 건물 입구 등 비를 피할 곳으로 안내
5. **다른 동네 확장:** `build_courses.py`, `enrich_courses.py`로 코스 구축 자동화
6. **실사용 검증:** 실제 보호자 대상 도보 테스트와 설명 문장 평가
