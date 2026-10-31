# 기능 정리

mungo(PawPath)가 해커톤 기간에 구현한 기능과 완성도의 기준 문서입니다. 2026-11-01, 커밋 `5f74f2d` 기준입니다. 화면에서의 사용법은 [기능 안내](GUIDE.md), 동작 원리는 [시스템 아키텍처](ARCHITECTURE.md)와 [추천 알고리즘](RECOMMENDER.md), 검증 방법과 결과는 [검증 결과](VALIDATION.md)에 있습니다.

## 상태 표기

구현 여부와 검증 여부를 따로 적습니다. 구현되어 있어도 실제 휴대폰이나 실제 사용자로 확인하지 않았으면 그렇게 적습니다.

| 구현 상태 | 뜻 |
|---|---|
| **Implemented** | 코드가 있고 화면이나 API로 쓸 수 있음 |
| **Partially Implemented** | 동작하지만 범위가 제한되거나 알려진 빈틈이 있음 |
| **Planned** | 코드는 없고, 팀 문서에 다음 단계로 적어 둔 것 |
| **Not Implemented** | 코드가 없고 계획도 정하지 않은 것 |

| 검증 상태 | 뜻 |
|---|---|
| **Verified** | 자동 테스트(pytest, Playwright)로 확인했거나 실제 외부 서비스에 연결해 확인함. 괄호에 방법 |
| **Partially Verified** | 일부 환경에서만 확인함(브라우저 위치 에뮬레이션, WebKit, 가짜 Google 서버 등) |
| **Not Verified** | 확인하지 않음 |

## 핵심 기능

mungo가 해결하려는 문제("오늘 이 아이와 언제, 어디로 걸어야 안전하고 즐거운가")에 직접 답하는 기능입니다.

| 기능 | 해결하려는 문제 | 사용자 가치 | 구현 내용 | 구현 상태 | 검증 상태 |
|---|---|---|---|---|---|
| 반려동물 특성 반영 | 같은 날씨와 코스라도 나이, 크기, 성격에 따라 적당한 산책이 다름 | 우리 아이 기준의 권장 시간, 거리, 쾌적 온도 | 크기, 나이, 체중, 활동량, 성격, 낯선 환경 반응, 더위 민감도를 생애 단계, 권장 시간·거리, 낯선 길·혼잡·오르막 허용도, 쾌적·위험 체감온도로 변환 | Implemented | Verified (pytest `test_features`, `test_recommender_v2` 3~5번) |
| 산책 시간 추천 | 시간마다 기온, 비, 바람, 자외선이 달라 언제 나갈지 판단하기 어려움 | "오늘 두부 산책은 오후 7시가 좋아요" 한 줄 답과 시간대별 점수 | 보호자 일정 안의 정시 출발 시각을 Open-Meteo 시간별 예보로 평가. 강한 비, 위험 체감온도, 강풍인 시간은 제외. 비 오기 전까지만 걷도록 시간 조정 | Implemented | Verified (pytest `test_timeslots`, 실제 Open-Meteo 연결) |
| 안전 선(先)필터 | 선호 점수가 높으면 위험한 코스가 상위에 오를 수 있음 | 위험한 코스는 개인화 점수와 관계없이 빠지고 이유가 보임 | 11개 항목(기온, 강수, 바람, 자외선, 시간대, 조명, 그늘, 차량 노출, 노면, 시설, 공원)을 양호·주의·위험·확인 불가로 평가. 위험 조건은 제외, 위험 수준은 뒤로. 데이터가 없는 항목은 안전으로 보지 않음 | Implemented | Verified (pytest `test_safety`, `test_recommender_v2` 6~9번, E2E 위험 코스 제외) |
| 코스 TOP 3 추천 | 코스 정보가 흩어져 있어 비교와 선택에 시간이 듦 | 출발 시각, 점수, 근거가 붙은 3개 코스 | 추천 v2: 반려견 특성 25%, 사용자 선호 25%, 거리·시간 20%, 날씨·환경 15% + 피드백 조정. 경로가 겹치는 코스는 한 번만, 다녀온 코스만 남으면 새 코스 하나 | Implemented | Verified (pytest `test_engine`, `test_course_scoring`, `test_recommender_v2` 14개 시나리오) |
| 피드백 학습 | 프로필만으로는 아이가 실제로 좋아하는 길을 알 수 없음 | 산책할수록 좋아한 코스와 시간대가 앞으로 옴. 변화 폭이 보임 | 만족도·재방문·난이도로 코스 선호(베이즈 축소 평균), 비슷한 코스 일반화(정규화 LMS), 시간대 선호, 선호 거리, 걸음 속도 학습. 피드백 조정은 최대 ±15점 | Implemented | Verified (pytest `test_preference`, `test_recommender_v2` 11~12번, E2E `scenario` 5점 피드백 후 다음 추천 반영) |
| 근거 있는 설명 | 추천 이유가 없으면 믿고 따르기 어려움 | 추천 문장, 항목별 점수 근거, 출처, 추정 여부 표시 | 계산 결과로만 문장 조립. 쓰지 않은 항목은 "반영하지 않았어요"로 표시 | Implemented | Verified (pytest `test_explain`) |
| AI 추천 문장 (선택) | 계산 문장은 딱딱함 | 근거를 지키면서 자연스러운 문장 | 로컬 Ollama(`gemma4:e4b`)가 점수를 뺀 근거로 문장만 다듬음. `explain_guard.py`가 이름, 길이, 단정 표현, 위치 표현, 근거 없는 시설·숫자를 검사해 통과한 문장만 사용 | Implemented (로컬 Ollama만) | Verified (pytest `test_llm`, 실제 Ollama로 3개 날씨 조건 확인). 품질의 통계적 평가는 Not Verified |
| GPS 길 안내 | 추천을 받아도 처음 가는 길은 찾아가기 어려움 | 출발점까지 도보 안내, 회전 방향, 진행률, 이탈 시 재탐색 | 출발점 3km 이내면 OSRM 도보 경로. 코스 위 진행도·회전·이탈(35m, 정확도에 따라 최대 60m)·완주 판정은 브라우저에서 계산 | Implemented | Partially Verified (Playwright 위치 에뮬레이션, 실제 OSRM). **실제 휴대폰 야외 도보는 Not Verified** |
| 산책 중 날씨 재평가 | 걷는 도중 날씨가 나빠져도 알기 어려움 | 복귀 경로와 대체 코스 안내 | 5분마다 또는 버튼으로 재평가. 시간별 예보 기반 | Implemented | Partially Verified (E2E 시연 시나리오). 실시간 강수 감지는 Not Implemented |

## 부가 기능

핵심 흐름을 넓히거나 운영에 필요한 기능입니다.

| 기능 | 해결하려는 문제 | 구현 내용 | 구현 상태 | 검증 상태 |
|---|---|---|---|---|
| 지도와 코스 비교 | 코스 조건을 한눈에 비교하기 어려움 | 조건 필터(오늘 추천, 30분 이하, 공원, 그늘), 거리·시간·그늘 비교 표, 주변 시설 8종과 출처·수집일 | Implemented | Verified (E2E `walk-navigation`, `scenario`) |
| 산책 기록과 피드백 | 학습에 쓸 실제 산책 결과가 필요함 | 만족도, 반려동물 만족도, 난이도, 날씨 만족도, 재방문 의향. 지난 시각 기록, 피드백 전 기록 삭제 | Implemented | Verified (E2E `walk-log`) |
| 주간 리포트 | 산책량 변화를 알기 어려움 | 횟수, 거리, 시간, 만족도 변화, 지난주 대비, 추천과 실제 선택 비교. 시연용 산책은 통계에서 제외 | Implemented | Verified (E2E 주간 리포트) |
| 여러 반려동물 | 반려동물마다 성향이 다름 | 반려동물별 추천, 기록, 학습 | Implemented | Verified (pytest) |
| 나만의 산책길 | 직접 걸은 길을 남기고 다시 쓰고 싶음 | GPS 기록(일시정지, 오차·순간 이동 거르기, 기기 임시 저장), 목록·상세·수정·삭제, 사진 5장(EXIF 제거) | Implemented | Partially Verified (Playwright 위치 에뮬레이션, WebKit). 실제 휴대폰 기록은 Not Verified |
| GPX 가져오기·내보내기 | 다른 앱의 기록을 쓰고 싶음 | GPX 1.0/1.1 읽기, 1.1 쓰기, XXE 차단, 10MB·10만 지점 제한 | Implemented | Verified (GPX 1.1 공식 스키마, gpxpy 상호 변환, 공개 GPX 51개) |
| 내 산책길을 추천 후보로 | 공용 코스만으로는 동네 길이 부족함 | 저장한 길이 내 전용 코스가 되어 같은 엔진으로 추천. 주변 환경은 Overpass로 측정 | Partially Implemented (혼잡도·경사는 측정하지 않음) | Verified (pytest `test_user_courses`, 실제 Overpass 측정값이 시드 코스와 일치) |
| 산책길 자동 만들기 | 정해진 코스가 없는 곳에서도 걷고 싶음 | 출발점과 시간으로 OSRM 순환 경로 후보 최대 5개. 반려동물을 고르면 서울 OSM 타일로 환경을 측정해 엔진으로 평가 | Implemented (경사·반려견 출입은 평가하지 않음) | Verified (pytest `test_route_generator`, `test_route_fit`, E2E `generate-route`) |
| 공유 링크 | 산책길을 다른 사람에게 보여 주고 싶음 | 추측할 수 없는 32자 토큰, 기간, 해제. 공유 화면에서 시각·정확도·반려동물·보호자 정보 제외 | Implemented | Verified (pytest `test_saved_walks`) |
| 산책길 커뮤니티 | 다른 보호자가 실제로 걸은 길을 찾기 어려움 | 출발·도착점 반경 가림 공유, 탐색·필터, 내 주변, 맞춤 추천, 좋아요·저장, 후기, 산책 인증, 공개용 GPX | Partially Implemented (신고·관리자 숨김 없음, 작성 횟수 제한 없음) | Partially Verified (pytest `test_community`, E2E Chromium·WebKit). 실제 휴대폰은 Not Verified |
| 공용 GPX 후보 코스 | 시드 코스가 동네 두 곳뿐임 | 공개 GPX 20개(서울 20개 구)를 적재. 서비스 지역 5km 안의 망원 4개, 개포 3개가 추천 후보 | Implemented | Verified (pytest `test_gpx_courses`) |
| 서비스 지역 | 발표장 근처에서 실제로 걸어 보려 함 | 망원동(기본), 개포동. 서버 설정 `SERVICE_AREA`로 전환 | Implemented | Verified (pytest `test_service_area`) |

## 계정과 운영

| 기능 | 구현 내용 | 구현 상태 | 검증 상태 |
|---|---|---|---|
| Google 로그인 | 유일한 로그인 방식. OpenID Connect 승인 코드 흐름(PKCE, state, nonce), HttpOnly 세션 쿠키. 처음 로그인하면 바로 가입 | Implemented | Verified (pytest `test_google_auth`는 가짜 Google 서버. 팀이 실제 Google 클라이언트로 개발 서버와 배포 주소에서 로그인 확인) |
| 로그인 없이 쓰기 | 기본(`AUTH_REQUIRED=false`)은 시연 보호자로 사용. `true`면 로그인 필수 | Implemented | Verified (pytest `test_auth`) |
| 계정별 데이터 분리 | 다른 계정의 반려동물, 추천, 기록, 산책길, 사진은 `404` | Implemented | Verified (pytest `test_account`, `test_api_e2e`) |
| 가족 프로필 | 계정 하나에 프로필 최대 5개. 반려동물과 학습은 공용, 기록은 프로필별 | Partially Implemented (프로필 잠금 없음, 지운 프로필 되살리기 화면 없음) | Verified (pytest `test_profiles`, E2E `profiles`) |
| 세션 만료와 본인 재확인 | 30일 또는 7일 미사용 시 만료. 탈퇴 전 Google 재확인(10분) | Implemented | Partially Verified (재확인은 가짜 Google 서버로만) |
| 계정 탈퇴 | 지울 데이터 표시, 유예 없이 즉시 삭제, 공유 차단. SQLite는 지운 행을 0으로 덮음 | Implemented | Verified (pytest `test_account`). PostgreSQL 파일 잔존은 Not Verified |
| 백업과 복구 (SQLite) | 24시간 자동 백업, 14일 보존, 검증, 복구 명령 | Implemented | Verified (pytest `test_backup`, 실제 서버 복구 훈련) |
| 백업 (PostgreSQL) | 배포 서버 cron이 `scripts/backup_postgres.sh`로 매일 `pg_dump`, 검증, 14일 보존. 복구는 수동 | Partially Implemented | Partially Verified (개발 DB로 백업·복구 확인) |
| PostgreSQL 전환 | Alembic 리비전, SQLite 데이터 이전 도구(`app.transfer`) | Implemented | Verified (팀 기록: 백엔드 테스트와 E2E를 PostgreSQL로 통과. 2026-11-01 재실행은 SQLite만) |
| 배포 | `compose.prod.yaml`(DB, API, nginx, OSRM, Cloudflare Tunnel) | Implemented | 팀 기록: https://pawpath.ficklebobo.dev 로 공개 운영 |

## Planned와 Not Implemented

| 기능 | 상태 | 이유 또는 현재 대안 |
|---|---|---|
| 학습 순위 모델(LightGBM 등) | Planned | 실제 피드백이 0건이라 바꿔 끼울 구조(`Ranker`)만 분리. 데이터가 쌓이면 규칙 기반과 같은 지표로 비교 ([머신러닝 도입 검토](RECOMMENDER.md#머신러닝-도입-검토)) |
| 실제 사용자 파일럿 | Planned | 선택률, 완주율, 만족도, 재이용을 측정할 계획. 지금 추천 지표는 시뮬레이션뿐 |
| 미세먼지 | Planned | 판단 기준(환경부 등급)만 있고 데이터 제공자 미연결. "확인 불가"로 표시 |
| 피드백 불만 이유 학습, 현재 위치 기반 거리 | Planned | [다음 제안](RECOMMENDER.md#향후-개선) |
| 화면이 꺼진 상태의 백그라운드 GPS 기록 | Not Implemented | 웹 브라우저의 한계. 끊긴 구간은 거리에서 빼고 안내 |
| 실시간 강수 감지 | Not Implemented | 시간별 예보로 판단하고 화면에 밝힘 |
| 카카오맵, 기상청 API | Not Implemented | Leaflet + OpenStreetMap, Open-Meteo 사용. 카카오맵은 길찾기 링크만 |
| 가로등, CCTV 공공데이터 | Not Implemented | 조명은 대부분 "확인 불가" |
| 관리자 기능, 커뮤니티 신고 | Not Implemented | 집계는 명령(`app.recommendation_report`)으로만 |
| 백업 원격 복사, 암호화 | Not Implemented | 파일 권한으로 막고, 다른 디스크를 지정할 수 있음 |
| 사용자의 지역 선택 | Not Implemented | 서버 설정으로만 전환 |
| 클라우드 LLM | Not Implemented | 로컬 Ollama만 |
| 아이디·비밀번호 로그인 | 제거 | 2026-11-01에 없애고 Google 로그인만 남김. 그때 로그인 시도 제한도 함께 사라짐 |

## 알려진 빈틈

| 영역 | 내용 |
|---|---|
| 실제 환경 | GPS 길 안내, 산책 기록, 커뮤니티를 실제 휴대폰으로 걸어 보지 않음. iPhone은 WebKit 엔진으로만 확인 |
| 휴대폰 Google 로그인 | 고정 도메인을 콘솔에 등록해야 함. 터널 환경에서는 확인하지 않음 |
| 코스 데이터 | 혼잡도, 그늘, 난이도는 팀 추정. 팀이 코스를 현장에서 걸어 보지 않음. OSM에 관계(relation)로 그린 큰 공원은 공원으로 잡히지 않음 |
| 커뮤니티 | 산책 인증은 브라우저가 보낸 GPS 기록을 믿으므로 API 직접 호출 위조는 막지 못함. 조회수 중복 방지 없음. 산책 중간에 들른 집은 가리지 못함. 글은 계정 단위라 프로필별로 나뉘지 않음 |
| PostgreSQL | 지운 행이 VACUUM 전까지 데이터 파일과 WAL에 남음. 시연 보호자 id 1 충돌은 시퀀스를 맞춰 고침 |
| 요청과 저장 | 크기 표시 없이 나눠 보내는(chunked) 큰 요청은 막지 못함. 사진은 DB에 바로 저장하고 업로드·가입 횟수 제한 없음 |
