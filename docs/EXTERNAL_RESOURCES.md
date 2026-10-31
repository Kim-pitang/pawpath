# 외부 자원 활용 내역

해커톤 가이드의 표 형식입니다. 발표자료의 "외부 자원 활용 내역" 페이지에 그대로 옮길 수 있습니다. 버전은 `backend/uv.lock`과 `frontend/package-lock.json`에 잠긴 값입니다.

| 구분 | 명칭 | 용도 | 라이선스 |
|---|---|---|---|
| 오픈소스 | FastAPI 0.162 | 백엔드 REST API | MIT |
| 오픈소스 | Uvicorn 0.54 | ASGI 서버 | BSD-3-Clause |
| 오픈소스 | SQLAlchemy 2.1 | ORM | MIT |
| 오픈소스 | Pydantic 2.14 / pydantic-settings 2.16 | 입력 검증, 환경변수 설정 | MIT |
| 오픈소스 | HTTPX 0.28 | 날씨 API 호출 | BSD-3-Clause |
| 오픈소스 | pytest 9.2 | 백엔드 테스트 | MIT |
| 오픈소스 | React 19.3 | 프론트엔드 UI | MIT |
| 오픈소스 | React Router 7.18 | 화면 라우팅 | MIT |
| 오픈소스 | Vite 6.4 | 프론트엔드 빌드 | MIT |
| 오픈소스 | TypeScript 5.9 | 정적 타입 | Apache-2.0 |
| 오픈소스 | Tailwind CSS 4.3 | 스타일 | MIT |
| 오픈소스 | Leaflet 1.9 | 지도 표시 | BSD-2-Clause |
| 오픈소스 | lucide-react 0.468 | 아이콘 | ISC |
| 오픈소스 | Pretendard 1.3 | 본문 글꼴 | OFL-1.1 |
| 오픈소스 | Jua (@fontsource/jua 5.3) | 브랜드 글꼴 | OFL-1.1 |
| 오픈소스 | Playwright 1.64 | 브라우저 E2E 테스트 (Chromium, WebKit) | Apache-2.0 |
| 오픈소스 | lxml 6.1 | GPX 1.1 스키마 검증 (개발 중 검증에만 사용, 앱에 포함하지 않음) | BSD-3-Clause |
| 오픈소스 | gpxpy 1.6 | 다른 GPX 도구와의 호환성 확인 (개발 중 검증에만 사용, 앱에 포함하지 않음) | Apache-2.0 |
| 외부 API | Open-Meteo Forecast API | 실시간 날씨와 시간별 예보 (실행 중 호출) | 비상업적 무료 이용, 데이터 CC BY 4.0 |
| 외부 API | OpenStreetMap 타일 서버 | 지도 배경 (실행 중 호출) | 데이터 ODbL, 타일 이용 정책 준수 |
| 외부 API | OSRM 도보 경로 (routing.openstreetmap.de) | 코스 경로 구축, 출발점 길찾기, 복귀 경로, 이탈 시 재탐색 (실행 중 호출) | 데이터 ODbL |
| 외부 API | 브라우저 Geolocation API | 현재 위치 수집, 산책 기록 (브라우저 내장) | 웹 표준 |
| 외부 API | Google OAuth 2.0 / OpenID Connect | Google 계정 로그인 (선택 기능, 설정했을 때만 실행 중 호출) | Google API 서비스 이용약관 |
| 외부 API | 브라우저 Web Share API, Clipboard API | 산책길 공유 링크 전달과 복사 (브라우저 내장) | 웹 표준 |
| 외부 API | Overpass API | 경로 주변 시설, 도로, 조명, 나무 기록 수집 (데이터 구축 시), 내 산책길을 저장해 추천 후보가 될 때 주변 환경 측정 (실행 중 호출) | 데이터 ODbL |
| 외부 API | OpenStreetMap Nominatim | 개포동 코스 제작 중 주소 확인 (개발 중 1회, 앱에서는 호출하지 않음) | 데이터 ODbL |
| 외부 API | Valhalla 공개 보행 경로 서버 (valhalla1.openstreetmap.de) | 서울 20개 구 GPX 후보 코스의 경로 계산 (데이터 구축 시 경유지 3개씩 20회, 앱에서는 호출하지 않음). 요청 URL은 GPX 자료의 `코스목록.csv`에 있음 | Valhalla MIT, 데이터 ODbL |
| 사전 보유 코드 | 없음 | 해당 없음 | 해당 없음 |
| 기타 | 카카오맵 길찾기 링크 | 출발점이 먼 경우 외부 지도로 연결 (사용자가 눌렀을 때만 이동, API 미사용) | 카카오맵 이용약관 |
| 기타 | OpenStreetMap 데이터 | 코스 경로, 주변 시설, 도로 유형, 조명, 노면, 나무 기록 | ODbL 1.0 |
| 기타 | 서울 반려견 산책 후보 GPX 20개 (Valhalla 응답 원본과 trkpt 변환본, 코스목록.csv) | 추천 후보 코스 20개(`backend/app/data/courses_gpx.json`)의 경로. 원본 zip은 저장소에 넣지 않음 | 데이터 ODbL (© OpenStreetMap contributors) |
| 기타 | Google "G" 로고 | Google 로그인 버튼 (Google 로그인 브랜드 지침에 따름) | Google 브랜드 지침 |
| 기타 | GPX 1.1 표준과 스키마 (TopoGrafix) | 가져오기와 내보내기 형식, 내보낸 파일 검증 | 공개 표준 |
| 기타 | gpxpy, togeojson 저장소의 공개 GPX 시험 파일 51개 | 실제 기기와 앱(스트라바, 애플워치, 가민 등)이 만든 GPX 호환성 확인. 개발 중 검증에만 쓰고 저장소에 포함하지 않음 | Apache-2.0, BSD-2-Clause |
| 기타 | Ollama 0.33 | 로컬 LLM 실행 (선택 기능) | MIT |
| 기타 | Gemma 4 (`gemma4:e4b`) | 추천 이유 문장 생성 (선택 기능) | Apache-2.0 |
| 기타 | 해커톤 제공 서버 (네이버 클라우드 플랫폼, SSL VPN 접속) | 일반 서버에서 앱 실행, GPU 서버(NVIDIA L4)에서 Ollama 실행. 2026-10-31~11-01 동작 확인용, 사설망 SSH 터널로만 접속 | 해커톤 운영 제공 자원 |
| 기타 | Claude Code (Anthropic) | AI 코딩 도구로 구현 전반에 활용 | 상용 서비스 |

## 직접 개발한 범위

- 추천 엔진 전체 (`backend/app/recommender`): 특성값 생성, 시간대 점수, 코스 6개 항목 점수, 적응형 가중치, 온라인 학습, 근거 기반 설명 생성
- 안전 지수 (`recommender/safety.py`), LLM 문장 사실 검증 (`recommender/explain_guard.py`)
- 추천 순위와 점수 계산에는 외부 AI 모델이나 LLM을 쓰지 않습니다. LLM은 선택 기능으로, 확정된 추천의 문장만 다듬습니다.
- GPS 길 안내 계산 (`frontend/src/lib/navigation.ts`): 경로 투영, 왕복 코스 진행도 추적, 회전 판정, 이탈과 완주 판정
- 산책 기록 계산 (`frontend/src/lib/recording.ts`): GPS 오차와 순간 이동 거르기, 일시정지와 끊김 구간 처리, 임시 저장과 복구
- GPX 읽기와 쓰기 (`backend/app/services/gpx_service.py`): 표준 라이브러리 expat 기반 파서, XXE 차단, GPX 1.1 생성. 별도 GPX 라이브러리를 쓰지 않음
- 계정 (`backend/app/services/auth_service.py`): 표준 라이브러리 scrypt 비밀번호 해시, 세션, 로그인 시도 제한. 별도 인증 라이브러리를 쓰지 않음
- Google 로그인 (`backend/app/services/google_auth_service.py`): OpenID Connect 승인 코드 흐름, PKCE, state, nonce, ID 토큰 확인. 별도 OAuth 라이브러리를 쓰지 않고 기존 HTTPX로 호출
- 계정 탈퇴와 삭제 (`backend/app/services/account_service.py`), 백업과 복구 (`backend/app/services/backup_service.py`): 표준 라이브러리 `sqlite3`의 온라인 백업만 쓰고, 외부 서비스나 백업 도구를 쓰지 않음
- 사진 메타데이터 제거 (`backend/app/services/photo_service.py`): JPEG와 PNG 파일 구조를 직접 읽어 위치 정보를 지움. 이미지 라이브러리를 쓰지 않음
- 코스 데이터 구축 스크립트, 백엔드 API, 프론트엔드 화면과 차트

## 확인이 필요한 항목

- **AI 코딩 도구 표기:** 팀이 쓴 다른 도구가 있으면 "기타" 행에 함께 적어 주세요.
- **Open-Meteo 이용 조건:** 무료 API는 비상업적 이용 기준입니다. 상용 서비스로 전환하면 유료 플랜이 필요합니다.
- **OSM 타일 서버:** 시연 수준의 이용을 전제로 합니다. 트래픽이 커지면 별도 타일 제공자로 바꿔야 합니다.
