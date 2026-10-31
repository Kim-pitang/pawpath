# 설치, 설정, 테스트

README의 [빠른 시작](../README.md#빠른-시작)을 넘어서는 실행 방법, 환경변수, 선택 기능, 테스트, 프로젝트 구조입니다. 배포 서버 구성은 [배포](DEPLOY.md), PostgreSQL 운영은 [PostgreSQL 운영](POSTGRES.md), 백업은 [백업 및 복구 정책](BACKUP.md)에 있습니다.

## 실행

필요 도구: Python 3.12 이상, [uv](https://docs.astral.sh/uv/), Node.js 20 이상. API 키는 필요 없습니다. `uv`가 Python도 자동으로 준비합니다.

`./dev.sh`는 의존성 설치(`uv sync`, `npm install`)부터 백엔드(8000)와 프론트엔드(5173) 실행까지 한 번에 하고, `Ctrl+C`로 함께 종료합니다. `.env` 없이 실행하면 Docker 없이 SQLite 파일(`backend/pawpath.db`)로 동작합니다.

`DATABASE_URL`이 이 컴퓨터의 PostgreSQL을 가리키면 `dev.sh`가 `docker compose`로 DB를 띄워 접속을 받을 때까지 기다린 뒤 서버를 띄웁니다. `Ctrl+C`로 백엔드와 프론트엔드를 종료해도 DB는 계속 돕니다(멈추려면 `docker compose stop`).

Windows에서는 PowerShell에서 `.\dev.ps1`을 실행합니다. 실행 정책 때문에 막히면 `powershell -ExecutionPolicy Bypass -File .\dev.ps1`로 실행하세요. `dev.ps1`은 DB 컨테이너를 띄우지 않으므로, PostgreSQL을 쓰려면 먼저 `docker compose up -d --wait`를 실행하세요.

### 처음 실행하면

테이블을 만들고(Alembic), 산책 코스(망원동 10개, 개포동 6개, 공개 GPX로 만든 서울 20개 구 코스 20개)와 시연용 반려동물 두부, 기본 일정(16~20시)을 넣습니다. GPX 코스는 출발점이 서비스 지역 5km 안이면 그 지역 추천 후보가 됩니다(망원동 4개, 개포동 3개). 적재 방법과 결과는 [GPX 후보 코스](GPX_COURSES.md)에 있습니다. 기본 지역은 망원동입니다. 이전 버전의 DB가 있으면 데이터를 유지한 채 구조를 자동으로 올립니다.

쓰던 SQLite 데이터를 PostgreSQL로 옮기려면 서버를 켜기 전에 `cd backend && uv run python -m app.transfer ./pawpath.db`를 실행하세요([절차](POSTGRES.md#sqlite-데이터-옮기기)).

### 따로 실행하기

```bash
# DB (PostgreSQL을 쓸 때)
docker compose up -d --wait

# 백엔드
cd backend
uv sync
uv run uvicorn app.main:app --port 8000

# 프론트엔드 (다른 터미널)
cd frontend
npm install
npm run dev
```

uv가 없다면 Python 3.12 가상환경을 켜고 `backend` 폴더에서 다음을 실행하세요.

```bash
pip install fastapi "uvicorn[standard]" sqlalchemy pydantic pydantic-settings httpx "psycopg[binary]" alembic
uvicorn app.main:app --port 8000
```

### 시연 데이터 지우기

SQLite로 실행한 경우 서버를 끄고 `backend/pawpath.db`를 삭제한 뒤 다시 실행하세요. PostgreSQL은 [PostgreSQL 운영](POSTGRES.md)을 참고하세요.

## 환경변수

설정 없이 바로 동작합니다. 값을 바꾸려면 저장소 최상위에 `.env`를 만들고 서버를 다시 시작하세요. 값을 비우거나 줄을 지우면 기본값을 씁니다. `.env`는 커밋하지 않습니다.

```bash
cp .env.example .env
```

| 변수 | 기본값 | 설명 |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./pawpath.db` | DB 주소. `.env.example`은 PostgreSQL(`postgresql+psycopg://...@localhost:5432/pawpath`) |
| `DB_POOL_SIZE` | `5` | PostgreSQL 연결 풀 크기 |
| `DB_MAX_OVERFLOW` | `10` | 풀이 찼을 때 더 여는 연결 수 |
| `DB_POOL_TIMEOUT_SECONDS` | `10` | 연결을 기다리는 최대 시간 |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT` | `pawpath`, 없음, `pawpath`, `5432` | 앱이 아니라 `docker compose`가 읽는 DB 컨테이너 설정. 비밀번호는 필수 |
| `WEATHER_PROVIDER` | `open-meteo` | `open-meteo` 또는 `mock` |
| `WEATHER_CACHE_MINUTES` | `30` | 실제 날씨 캐시 시간 |
| `WEATHER_TIMEOUT_SECONDS` | `5` | 날씨 API 제한 시간 |
| `ROUTING_PROVIDER` | `osrm` | 도보 길찾기. `none`이면 직선으로 표시 |
| `ROUTING_BASE_URL` | `https://routing.openstreetmap.de/routed-foot` | OSRM 도보 경로 서버 |
| `ROUTING_TIMEOUT_SECONDS` | `4` | 길찾기 제한 시간 |
| `ROUTING_MAX_DISTANCE_KM` | `3` | 이보다 멀면 도보 안내 대신 카카오맵 길찾기를 안내 |
| `ROUTING_MIN_INTERVAL_SECONDS` | `1.1` | 산책길 자동 생성이 길찾기 서버를 부르는 최소 간격(초). 공용 서버는 초당 1회 안내라 1.1. 직접 띄운 OSRM이면 `0` |
| `GENERATION_MAX_SECONDS` | `30` | 산책길 한 번 생성에 쓰는 최대 시간(초). 넘으면 그때까지의 후보로 마침 |
| `GENERATION_COOLDOWN_SECONDS` | `10` | 같은 계정이 산책길을 다시 만들기까지 기다리는 시간(초). 직접 띄운 OSRM이면 줄여도 됨 |
| `GENERATION_BEARINGS` | `8` | 경로를 만들 때 시도하는 방위 수(4~72). 동서남북을 먼저 시도하고 나머지는 균등 간격 |
| `GENERATION_RADIUS_SCALES` | `1.0` | 경유점 거리 배율(쉼표 구분, 0.5~1.5). 값마다 방위 수만큼 더 시도. 첫 값이 기본 모양 |
| `GENERATION_SPREADS` | `30` | 경유점 두 개가 방위 양옆으로 벌어지는 각도(쉼표 구분, 10~60도). 값마다 더 시도. 첫 값이 기본 모양 |
| `GENERATION_MAX_REQUESTS` | `11` | 길찾기 요청 상한(4~300). 시도 수 = 방위 × 배율 × 각도, 후보가 모자라면 보정 요청 몇 번 추가. 늘리면 `GENERATION_MAX_SECONDS`도 함께 올릴 것(기본 30초는 요청 약 27회에서 끝남) |
| `GENERATION_POOL_SIZE` | `5` | 반려동물 평가 전에 남기는 서로 다른 후보 수. 평가 후 점수 높은 순으로 `GENERATION_MAX_RESULTS`개만 보여 줌 |
| `GENERATION_MAX_RESULTS` | `5` | 화면에 돌려주는 후보 수(1~10) |
| `ENVIRONMENT_PROVIDER` | `overpass` | 내 산책길을 추천 후보로 등록할 때 주변 환경을 OSM에서 측정. `none`이면 측정하지 않고 "확인 불가"로 표시. 산책길 만들기의 후보 평가는 이 값과 무관하게 pbf에서 미리 뽑아 둔 `backend/app/data/osm/<지역>/`(타일)을 쓴다(갱신: `scripts/extract_osm_tiles.py`, osmium-tool 필요, 서울 기준 15초. 저장소에는 서울만 있고 경기는 `python scripts/extract_osm_tiles.py gyeonggi <경기 pbf>`로 만든다) |
| `RECOMMENDER_WEIGHTS` | (비움) | 추천 가중치 JSON. v2 예: `{"pet_fit":0.3,"feedback":0.1}`, v1 예: `{"weather":0.3,"safety":0.2}`. 잘못된 값이면 기본 가중치를 씀 |
| `RECOMMENDER_VERSION` | `v2` | 추천 알고리즘. `v2`는 안전 단계를 먼저 적용하는 5개 묶음 모델, `v1`은 이전 6항목 가중합. 자세한 내용은 [추천 알고리즘](RECOMMENDER.md) |
| `LLM_PROVIDER` | `none` | 추천 문장 생성. `ollama`면 로컬 LLM 사용 |
| `LLM_BASE_URL` | `http://localhost:11434` | Ollama 주소 |
| `LLM_MODEL` | `gemma4:e4b` | 사용할 모델 |
| `LLM_TIMEOUT_SECONDS` | `60` | LLM 제한 시간 |
| `SERVICE_AREA` | `mangwon` | 서비스 지역: `mangwon`(망원동) 또는 `gaepo`(개포동). [개포동 코스로 전환](#개포동-코스로-전환) 참고 |
| `SERVICE_LATITUDE`, `SERVICE_LONGITUDE` | 서비스 지역의 좌표 | 날씨를 조회할 좌표 |
| `SERVICE_TIMEZONE` | `Asia/Seoul` | 서비스 시간대 |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 허용할 프론트엔드 주소 |
| `SEED_DEMO_PET` | `true` | 첫 실행 때 두부 생성 여부 |
| `AUTH_REQUIRED` | `false` | `true`면 로그인해야 앱을 쓸 수 있음. `false`면 로그인하지 않은 사용자는 시연 보호자로 동작하고, 로그인한 보호자의 데이터는 따로 관리 |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | 비어 있음 | Google 로그인용 OAuth 클라이언트 값. 둘 다 넣어야 켜짐. [Google 로그인 켜기](#google-로그인-켜기) 참고 |
| `GOOGLE_REDIRECT_URI` | `http://localhost:5173/api/auth/google/callback` | Google 콘솔에 등록한 리디렉션 URI와 같아야 함 |
| `E2E_LOGIN` | `false` | `true`면 테스트 전용 로그인(`POST /api/e2e/login`)을 엶. E2E 테스트용이며 운영 서버에서는 켜지 않음 |
| `BACKUP_ENABLED` | `true` | SQLite DB 자동 백업(PostgreSQL은 `pg_dump`). [백업 및 복구 정책](BACKUP.md) 참고 |
| `BACKUP_DIR` | `./backups` | DB 사본과 탈퇴 기록을 둘 폴더. 디스크 장애에 대비하려면 다른 디스크로 지정 |
| `BACKUP_INTERVAL_HOURS` | `24` | 자동 백업 간격 |
| `BACKUP_RETENTION_DAYS` | `14` | 이 기간이 지난 백업을 지움. 탈퇴한 보호자의 데이터가 백업에 남는 최대 기간이기도 함 |

## AI 추천 문장 켜기

기본값은 꺼짐이며, 꺼져 있어도 나머지 기능은 모두 동작합니다. 켜려면 [Ollama](https://ollama.com)를 실행하고 모델을 받습니다. API 키는 필요 없습니다.

```bash
ollama pull gemma4:e4b
```

그다음 `.env`에 아래 값을 넣고 서버를 다시 시작합니다. 다른 모델을 쓰려면 `LLM_MODEL`을 바꾸세요.

```
LLM_PROVIDER=ollama
```

추천 화면은 계산 결과로 만든 문장을 먼저 보여 주고, 사실 검증을 통과한 AI 문장이 오면 바꿉니다. LLM이 응답하지 않거나 근거 없는 내용을 쓰면 처음 문장을 그대로 씁니다.

## Google 로그인 켜기

Google 클라이언트 값을 넣으면 로그인 화면에 **Google로 계속하기** 버튼이 생깁니다. 값이 없으면 버튼이 보이지 않고, 로그인 없이 시연 보호자로만 씁니다.

1. [Google Cloud 콘솔](https://console.cloud.google.com/)에서 프로젝트를 만듭니다.
2. **Google 인증 플랫폼**(OAuth 동의 화면)에서 앱 이름과 지원 이메일을 넣고, 대상을 **외부**로 정합니다. 게시하기 전에는 **테스트 사용자**에 넣은 Google 계정만 로그인할 수 있으니 시연할 계정을 추가하세요.
3. **클라이언트 > 클라이언트 만들기**에서 유형을 **웹 애플리케이션**으로 고르고, **승인된 리디렉션 URI**에 `http://localhost:5173/api/auth/google/callback`을 넣습니다.
4. 발급된 클라이언트 ID와 보안 비밀을 `.env`에 넣고 서버를 다시 시작합니다.

```
GOOGLE_CLIENT_ID=123456789-xxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxx
```

5. 앱을 **`http://localhost:5173`**으로 엽니다. `127.0.0.1:5173`으로 열면 돌아오는 주소와 호스트가 달라 "시작한 주소와 돌아온 주소가 달라요" 오류가 납니다.

휴대폰에서 터널로 쓰려면 고정 주소가 필요합니다. `cloudflared tunnel --url`의 임시 주소는 실행할 때마다 바뀌어 매번 콘솔에 등록해야 하므로, 고정 도메인(이름 있는 Cloudflare 터널이나 ngrok 고정 도메인)의 `https://도메인/api/auth/google/callback`을 콘솔에 등록하고 같은 값을 `GOOGLE_REDIRECT_URI`에 넣으세요.

E2E 테스트는 Google 화면을 지날 수 없어 `E2E_LOGIN=true`로 여는 테스트 전용 로그인을 씁니다. 운영 서버에서는 켜지 마세요. 로그인한 뒤의 동작은 [기능 안내](GUIDE.md#2-로그인-및-계정)에 있습니다.

## 개포동 코스로 전환

기본 지역은 망원동입니다. 발표 장소인 개포디지털혁신파크 새롬관 근처에서 실제 GPS로 걸어 보려면 개포동 코스로 전환하세요. 서버를 끄고 아래처럼 다시 실행합니다.

```bash
SERVICE_AREA=gaepo ./dev.sh
```

계속 쓰려면 `.env`에 `SERVICE_AREA=gaepo`를 넣으세요. 추천, 지도, 대체 코스가 이 지역의 코스만 쓰고 날씨 좌표도 함께 바뀝니다. 코스와 산책 기록은 DB에 모두 남으므로 지역을 바꿔도 지워지지 않습니다.

| 코스 | 거리 | 예상 시간 | 특징 |
|---|---|---|---|
| 개포동 근린공원 양재천변 코스 | 1.35km | 20분 | 공원과 강변길, 일상 코스 |
| 개포로88길 골목 코스 | 0.96km | 15분 | 동네 골목, 일상 코스. 큰길로 표시된 구간이 24% |
| 양재천 영동6교 왕복 | 1.65km | 30분 | 강변길 왕복, 일상 코스 |
| 양재천 서쪽 강변 왕복 | 2.36km | 40분 | 강변길 왕복 |
| 달터근린공원 숲길 | 2.34km | 40분 | 흙길이 있는 숲길. 출발점이 발표장에서 약 1.5km |
| 양재천 탄천 종주 코스 | 4.24km | 70분 | 탄천 자전거길까지 왕복하는 긴 코스 |

경로와 시설은 OpenStreetMap 기준이며, 혼잡도와 그늘 같은 추정값은 현장에서 확인한 값이 아닙니다.

## 휴대폰에서 실제 GPS 쓰기

**브라우저는 HTTPS나 localhost에서만 위치 정보를 허용합니다.** 같은 컴퓨터의 `http://localhost:5173`에서는 바로 동작하지만, 휴대폰에서 `http://192.168.x.x:5173`으로 접속하면 막힙니다. 휴대폰에서 실제 GPS를 쓰려면 HTTPS 터널을 여세요. Vite 설정에 아래 두 도구의 주소를 허용해 두었습니다.

```bash
./dev.sh
cloudflared tunnel --url http://localhost:5173   # 또는: ngrok http 5173
# 출력된 https 주소를 휴대폰에서 엽니다
```

## 테스트

```bash
# 백엔드 단위 테스트와 API E2E (기본은 임시 SQLite)
(cd backend && uv sync && uv run pytest)

# 같은 테스트를 PostgreSQL 테스트 DB로 (테이블을 지우므로 pawpath_test만 넣으세요)
(cd backend && TEST_DATABASE_URL=postgresql+psycopg://pawpath:비밀번호@localhost:5432/pawpath_test uv run pytest)

# 브라우저 E2E (임시 DB와 Mock 날씨로 서버를 직접 띄움)
(cd frontend && npm install && npx playwright install chromium && npm run test:e2e)
```

브라우저 E2E는 8010, 5183 포트에 서버를 직접 띄웁니다. 고도화 시나리오 12개, 나만의 산책길 예외 항목 14개, 산책길 커뮤니티 항목의 결과는 [검증 결과](VALIDATION.md)에 있습니다. 같은 E2E를 iPhone 13 WebKit으로도 돌려 확인했습니다.

추천 지표는 아래 명령으로 볼 수 있습니다. `offline`은 DB를 쓰지 않는 v1, v2 비교이고 실제 사용자 성능이 아닙니다. 결과와 한계는 [추천 알고리즘](RECOMMENDER.md)에 있습니다.

```bash
(cd backend && uv run python -m app.recommendation_report online)   # 실제 기록 집계
(cd backend && uv run python -m app.recommendation_report offline)  # 조건 조합과 합성 사용자 비교 (몇 분 걸림)
```

## 프로젝트 구조

```
backend/
  app/
    recommender/     추천 엔진: 특성값, 시간대, 코스 점수, 안전 지수, 학습, 설명
    services/        날씨, 길찾기, LLM, 대체 경로, 리포트, 시설 검색, GPX, 나만의 산책길, 커뮤니티, 계정, 탈퇴, 백업, 사진
    data/            산책 코스와 주변 시설 시드
    api.py, models.py, schemas.py, migrations.py, seed.py, main.py, backup.py, transfer.py
  alembic/           DB 구조 변경 리비전
  tests/             단위 테스트, API E2E, 검증 시나리오
frontend/
  src/pages/         화면
  src/components/    지도, 차트, 안전 평가, 공통 UI
  src/lib/           API 호출, 길 안내 계산, 위치 수집, 산책 기록 계산
  e2e/               브라우저 E2E
scripts/             코스 경로 구축(build_courses.py), OSM 환경값 계산(enrich_courses.py), 환경 타일 추출(extract_osm_tiles.py), 테스트 DB 초기화(postgres-init/), 배포 DB 백업(backup_postgres.sh)
docs/                아키텍처, API 명세, 추천 알고리즘, 기능 안내, 설치와 설정, 검증 결과, 백업, PostgreSQL, 배포, GPX 코스, 외부 자원
docker-compose.yml   개발용 PostgreSQL
compose.prod.yaml    배포용 DB, API, 웹(nginx), 길찾기, 터널
dev.ps1, dev.sh      개발 서버를 한 번에 띄우는 스크립트 (Windows, macOS/Linux)
PRODUCT.md           제품 정의, 사용자, 브랜드(mungo)와 디자인 원칙
```
