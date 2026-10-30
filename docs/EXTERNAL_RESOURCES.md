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
| 오픈소스 | Playwright 1.64 | 브라우저 E2E 테스트 | Apache-2.0 |
| 외부 API | Open-Meteo Forecast API | 실시간 날씨와 시간별 예보 (실행 중 호출) | 비상업적 무료 이용, 데이터 CC BY 4.0 |
| 외부 API | OpenStreetMap 타일 서버 | 지도 배경 (실행 중 호출) | 데이터 ODbL, 타일 이용 정책 준수 |
| 외부 API | OSRM 도보 경로 (routing.openstreetmap.de) | 코스 경로 구축, 현재 위치에서 출발점까지 길찾기 (실행 중 호출) | 데이터 ODbL |
| 외부 API | 브라우저 Geolocation API | 현재 위치 수집 (브라우저 내장) | 웹 표준 |
| 외부 API | Overpass API | 경로 주변 시설 수집 (데이터 구축 시 1회) | 데이터 ODbL |
| 사전 보유 코드 | 없음 | 해당 없음 | 해당 없음 |
| 기타 | 카카오맵 길찾기 링크 | 출발점이 먼 경우 외부 지도로 연결 (사용자가 눌렀을 때만 이동, API 미사용) | 카카오맵 이용약관 |
| 기타 | OpenStreetMap 데이터 | 코스 경로, 공원, 화장실, 음수대, 동물병원 위치 | ODbL 1.0 |
| 기타 | Claude Code (Anthropic) | AI 코딩 도구로 구현 전반에 활용 | 상용 서비스 |

## 직접 개발한 범위

- 추천 엔진 전체 (`backend/app/recommender`): 특성값 생성, 시간대 점수, 코스 6개 항목 점수, 적응형 가중치, 온라인 학습, 근거 기반 설명 생성
- 외부 AI 모델이나 LLM API를 추천에 사용하지 않습니다.
- GPS 길 안내 계산 (`frontend/src/lib/navigation.ts`): 경로 투영, 왕복 코스 진행도 추적, 회전 판정, 이탈과 완주 판정
- 코스 데이터 구축 스크립트, 백엔드 API, 프론트엔드 화면과 차트

## 확인이 필요한 항목

- **AI 코딩 도구 표기:** 팀이 쓴 다른 도구가 있으면 "기타" 행에 함께 적어 주세요.
- **Open-Meteo 이용 조건:** 무료 API는 비상업적 이용 기준입니다. 상용 서비스로 전환하면 유료 플랜이 필요합니다.
- **OSM 타일 서버:** 시연 수준의 이용을 전제로 합니다. 트래픽이 커지면 별도 타일 제공자로 바꿔야 합니다.
