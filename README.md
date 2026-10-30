# PawPath 댕댕 산책각

**Every Paw Deserves a Perfect Path.**

AI-Powered Personalized Pet Walking Recommendation

PawPath는 반려동물의 나이, 크기, 활동량, 성격, 산책 선호도와 보호자의 일정을 분석하고, 실시간 날씨와 동네 환경을 고려해 오늘 가장 좋은 산책 시간과 코스를 추천하는 서비스입니다. 산책 후 남긴 피드백을 학습해 반려동물이 실제로 좋아하는 코스와 시간대를 다음 추천에 반영합니다.

> 낯선 길을 싫어하는 두부를 위해 익숙한 공원 코스를 골랐어요. 비가 오기 전 짧게 다녀올 수 있어요.

위 문장은 고정 문구가 아니라 두부의 프로필, 코스 데이터, 시간별 예보로 계산해 만든 결과입니다.

## 핵심 기능

- **펫밸런스:** 프로필에서 권장 산책량과 성향 값을 계산해 산책 시간과 강도를 맞춥니다.
- **비켜비:** 시간별 강수, 기온, 바람, 자외선을 반려동물 기준으로 평가해 궂은 시간을 피합니다.
- **안심귀가:** 해가 진 뒤에는 조명 비중을 높이고, 공원과 확인된 시설을 함께 평가합니다.
- **피드백 학습:** 코스 선호도와 시간대 선호를 학습하고, 비슷한 코스로 일반화합니다.
- **근거 있는 설명:** 추천 이유와 주의사항을 실제 데이터로만 만듭니다. 추정값은 추정이라고 표시합니다.

## 빠른 시작

필요 도구: Python 3.12 이상과 [uv](https://docs.astral.sh/uv/), Node.js 20 이상. API 키는 필요 없습니다.

```bash
./dev.sh
```

- 앱: http://localhost:5173
- API 문서(Swagger): http://localhost:8000/docs

처음 실행하면 DB(`backend/pawpath.db`)를 만들고, 산책 코스 10개와 시연용 반려동물 두부, 기본 일정(16~20시)을 넣습니다.

### 따로 실행하기

```bash
# 백엔드
cd backend
uv sync
uv run uvicorn app.main:app --port 8000

# 프론트엔드 (다른 터미널)
cd frontend
npm install
npm run dev
```

uv가 없다면 Python 3.12 가상환경에서 `pip install fastapi "uvicorn[standard]" sqlalchemy pydantic pydantic-settings httpx`로 설치한 뒤 같은 `uvicorn` 명령을 실행하세요.

## 환경변수

`.env.example`을 복사해 `.env`로 쓰면 됩니다. 모두 선택 사항이며 기본값으로 동작합니다. `.env`는 커밋하지 않습니다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./pawpath.db` | DB 주소 |
| `WEATHER_PROVIDER` | `open-meteo` | `open-meteo` 또는 `mock` |
| `WEATHER_CACHE_MINUTES` | `30` | 실제 날씨 캐시 시간 |
| `WEATHER_TIMEOUT_SECONDS` | `5` | 날씨 API 제한 시간 |
| `SERVICE_LATITUDE`, `SERVICE_LONGITUDE` | `37.5560`, `126.9105` | 서비스 지역 (망원동) |
| `SERVICE_TIMEZONE` | `Asia/Seoul` | 서비스 시간대 |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 허용할 프론트엔드 주소 |
| `SEED_DEMO_PET` | `true` | 첫 실행 때 두부 생성 여부 |

## 시연 순서

1. **홈:** 두부 정보, 현재 날씨, 산책 가능 시간을 확인하고 **추천 시작**을 누릅니다.
2. **추천:** 날씨 조건에서 **곧 비**를 고릅니다. 위의 추천 문장과 TOP 3, 점수 근거를 볼 수 있습니다. 어느 시각에 시연해도 같은 문장이 나옵니다.
3. **지도:** 코스 경로와 공원, 화장실 같은 시설을 확인합니다.
4. **산책:** 2위 코스에서 **이 코스로 산책** → **산책 완료** → 만족도 5점 피드백을 남깁니다.
5. **달라진 추천 보기:** 피드백한 코스가 1위로 오르고 "학습 효과"와 순위 변화가 표시됩니다.
6. **마이페이지:** 코스 선호도, 학습된 취향, 추천 결과 변화를 확인합니다.

**실제 날씨** 외의 조건(곧 비, 폭염, 한파, 폭우)은 시연용 시나리오이며 화면에 그렇게 표시됩니다. 폭염에서는 더운 시간이 제외되고, 폭우에서는 실내 대안을 안내합니다. 시연 내용을 지우려면 서버를 끄고 `backend/pawpath.db`를 삭제한 뒤 다시 실행하세요.

## 테스트

```bash
# 백엔드 단위 테스트와 API E2E
cd backend && uv run pytest

# 브라우저 E2E (임시 DB와 Mock 날씨로 서버를 직접 띄움)
cd frontend
npx playwright install chromium
npm run test:e2e
```

## 프로젝트 구조

```
backend/
  app/
    recommender/     추천 엔진: 특성값, 시간대, 코스 점수, 학습, 설명
    services/        날씨 제공자와 폴백, 추천·피드백 처리
    data/courses.json 산책 코스 시드
    api.py, models.py, schemas.py, seed.py, main.py
  tests/             단위 테스트, API E2E
frontend/
  src/pages/         화면
  src/components/    지도, 차트, 공통 UI
  e2e/               브라우저 E2E
scripts/build_courses.py  코스 데이터 구축 스크립트
docs/                아키텍처, API 명세, 외부 자원, 개발 계획
```

## 문서

- [시스템 아키텍처](docs/ARCHITECTURE.md): 구성, 추천 알고리즘, 데이터 모델, 장애 대응
- [API 명세](docs/API.md)
- [외부 자원 활용 내역](docs/EXTERNAL_RESOURCES.md): 발표자료용 표
- [개발 계획](docs/PLAN.md)

## 데이터와 안전에 관한 안내

- 코스 경로와 화장실, 음수대, 동물병원, 공원 위치는 OpenStreetMap 기준입니다.
- 혼잡도, 조명, 그늘, 차량 노출, 노면, 난이도, 동반 가능 여부는 팀 추정값이며 현장 확인이 필요합니다. 코스 10개는 시연용으로 만든 것이며 팀이 현장에서 걸어 보며 확인한 것은 아닙니다.
- 날씨 적합도는 수의학적 안전 진단이 아닙니다. 반려동물의 건강 상태와 현장 상황을 먼저 살펴 주세요.

## 구현 범위

| 구분 | 상태 |
|---|---|
| 프로필, 일정, 날씨, 코스, 시간 추천, 코스 추천, 추천 이유, 피드백 학습 | 구현 |
| 지도 경로와 시설 표시, 산책 기록, 선호도 변화 시각화 | 구현 |
| 산책 통계, 다중 반려동물 | 구현 |
| LLM 추천 설명 | 미구현: 근거 기반 템플릿 사용 |
| 별도 산책 리포트 | 미구현: 마이페이지 분석으로 대체 |
| 로그인 | 미구현: 기본 보호자 1명으로 동작 |
| Kakao Maps, 기상청 API | 미구현: Leaflet + OSM, Open-Meteo 사용. 날씨는 `WeatherProvider` 프로토콜로 교체 가능 |
| PostgreSQL | 설정만 지원, 연결 미검증 |

지도 데이터 © OpenStreetMap contributors. 날씨 데이터 Open-Meteo.
