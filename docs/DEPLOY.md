# 배포

배포 서버에서 DB, API, 웹, 길찾기를 모두 컨테이너로 돌립니다. 정의는 저장소 최상위의 `compose.prod.yaml`입니다. 개발용 `docker-compose.yml`(DB만)과는 이름(`pawpath-prod`)과 볼륨이 달라 섞이지 않습니다. 로컬 개발 실행은 [설치, 설정, 테스트](SETUP.md)를, 로컬과 배포의 DB 차이는 [PostgreSQL 운영](POSTGRES.md)을 보세요.

| 서비스 | 이미지 | 하는 일 | 밖으로 여는 포트 |
|---|---|---|---|
| `db` | `postgres:18.6-bookworm` | 데이터 | 없음 |
| `backend` | `backend/Dockerfile` (Python 3.12, uv) | API. 켜질 때 Alembic으로 구조를 올리고 시드를 넣음 | 없음 |
| `web` | `frontend/Dockerfile` (빌드 후 nginx 1.30) | 화면, `/api`와 `/docs`를 backend로 넘김 | `127.0.0.1:5173` |
| `osrm` | `osrm-backend` (digest 고정) | 도보 길찾기. `COMPOSE_PROFILES=osrm`일 때만 | `127.0.0.1:5002` |
| `cloudflared` | `cloudflare/cloudflared:2026.5.2` | 바깥 공개(Cloudflare Tunnel). `COMPOSE_PROFILES`에 `tunnel`이 있을 때만 | 없음(서버가 Cloudflare로 나가는 연결만 씀) |

모든 포트를 서버 안(127.0.0.1)에서만 엽니다. 바깥 사용자는 Cloudflare Tunnel로 `https://pawpath.ficklebobo.dev`에 들어옵니다. 서버는 내부망이라 인바운드가 없고, 터널은 아웃바운드 7844만 씁니다.

## 바깥 공개 (Cloudflare Tunnel)

1. Cloudflare 대시보드 Networking → Tunnels에서 터널을 만들고 토큰(`eyJ...`)을 받는다. 대시보드가 보여 주는 `docker run` 명령은 실행하지 않는다.
2. 터널의 Routes에 Published application을 추가한다. 주소는 `pawpath.ficklebobo.dev`, Service URL은 `http://web:80`(끝에 `/`를 붙이면 추가가 거부된다).
3. `.env`에 `CLOUDFLARE_TUNNEL_TOKEN`을 넣고 `COMPOSE_PROFILES`에 `tunnel`을 더한 뒤 `docker compose -f compose.prod.yaml up -d --wait`.
4. 공개 주소가 바뀌면 `.env`의 `GOOGLE_REDIRECT_URI`와 Google 콘솔의 승인된 리디렉션 URI를 같이 바꾼다.

## .env

앱 설정은 `.env.example`과 같습니다. 배포에서 더 쓰는 값:

| 변수 | 예 | 설명 |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `pawpath`, (비밀), `pawpath` | DB 계정. backend의 `DATABASE_URL`은 이 값으로 compose가 만듭니다(.env의 `DATABASE_URL`은 쓰지 않음) |
| `PG_VOLUME` | `pawpath-postgres-data` | 이미 있는 DB 볼륨을 쓸 때. 비우면 `pawpath-prod-pgdata` |
| `WEB_PORT` | `5173` | 웹을 여는 포트 |
| `COMPOSE_PROFILES` | `osrm,ollama-relay,tunnel` | 길찾기 컨테이너(`osrm`), 127.0.0.1에만 열린 Ollama 터널을 컨테이너에 이어 주는 중계(`ollama-relay`), 바깥 공개(`tunnel`)도 띄울 때 |
| `CLOUDFLARE_TUNNEL_TOKEN` | (비밀) | Cloudflare Tunnel 토큰. `tunnel` 프로필에서 씀 |
| `GOOGLE_REDIRECT_URI` | `https://pawpath.ficklebobo.dev/api/auth/google/callback` | 공개 주소 기준. Google 콘솔에도 같은 값을 등록 |
| `OSRM_DATA_DIR`, `OSRM_DATASET` | `/home1/ncloud/pawpath-osrm/releases/...`, `gyeonggi` | 길찾기 데이터 위치와 이름 |
| `PROD_LLM_BASE_URL` | `http://host.docker.internal:11434` | 서버의 Ollama. 컨테이너 안의 localhost는 컨테이너 자신입니다 |

## 처음 배포하기 (SQLite 데이터가 있을 때)

```bash
git pull --ff-only
# 1. 쓰던 서버를 멈춘다(옮기는 동안 데이터가 바뀌지 않게)
# 2. DB만 띄운다. backend를 먼저 띄우면 시드가 들어가 이전이 거부된다
docker compose -f compose.prod.yaml up -d --wait db
# 3. 옮긴다. 원본은 읽기 전용으로 붙이고, 백업은 backups 볼륨에 남는다
mkdir -p ~/pawpath-import && cp backend/pawpath.db ~/pawpath-import/ && chmod 644 ~/pawpath-import/pawpath.db
docker compose -f compose.prod.yaml run --rm --no-deps -v ~/pawpath-import:/import:ro backend python -m app.transfer /import/pawpath.db
# 4. 나머지를 띄운다
docker compose -f compose.prod.yaml up -d --build --wait
```

## 고친 코드 배포하기

```bash
git pull --ff-only
docker compose -f compose.prod.yaml up -d --build --wait
```

구조 변경(Alembic 리비전)은 backend가 켜질 때 적용됩니다.

## 백업

`scripts/backup_postgres.sh`가 `pg_dump`로 `~/pawpath-backups`에 백업하고, 읽을 수 있는지 확인한 뒤, 14일이 지난 백업을 지웁니다. 서버의 cron이 매일 04:30에 부릅니다.

```bash
crontab -l   # 30 4 * * * /home1/ncloud/pawpath/scripts/backup_postgres.sh >> /home1/ncloud/pawpath-backups/backup.log 2>&1
```

복구는 [PostgreSQL 운영](POSTGRES.md#백업과-복구)의 `pg_restore` 절차를 따르되, 명령의 `docker compose`를 `docker compose -f compose.prod.yaml`로 바꿉니다.

## 상태 보기

```bash
docker compose -f compose.prod.yaml ps
docker compose -f compose.prod.yaml logs -f backend
curl -s localhost:5173/api/health
```
