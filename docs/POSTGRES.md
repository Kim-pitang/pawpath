# PostgreSQL 운영

개발과 배포 모두 PostgreSQL 18(`postgres:18.6-bookworm`)을 씁니다. 개발 DB는 저장소 최상위의 `docker-compose.yml`로 띄우고, 배포 서버는 `compose.prod.yaml`에서 같은 이미지를 씁니다([배포](DEPLOY.md)). SQLite는 Docker 없이 돌리는 경우와 기본 테스트용으로 남아 있습니다.

## 처음 띄우기

```bash
cp .env.example .env        # POSTGRES_PASSWORD와 DATABASE_URL의 비밀번호를 같은 값으로 바꾸세요
docker compose up -d --wait # 접속을 받을 때까지 기다린 뒤 끝남
./dev.sh                    # DATABASE_URL이 이 컴퓨터의 PostgreSQL이면 위 명령을 대신 실행함
```

| 항목 | 값 |
|---|---|
| 접속 | `127.0.0.1:5432`에서만 엽니다. 다른 컴퓨터에서는 접속할 수 없습니다 |
| DB | `pawpath`(개발), `pawpath_test`(테스트. 테이블을 지우고 다시 만듦). 볼륨을 처음 만들 때 `scripts/postgres-init`이 테스트 DB를 만듭니다 |
| 데이터 | `pawpath-pgdata` 볼륨. `docker compose down`으로는 지워지지 않고, `down -v`를 하면 지워집니다 |
| 인코딩 | UTF-8, 로캘 `C.UTF-8`. 한글 정렬이 컴퓨터마다 달라지지 않습니다 |
| 상태 확인 | `pg_isready` 헬스 체크. `docker compose ps`에 `healthy`로 보입니다 |
| 연결 풀 | 서버 한 대가 최대 `DB_POOL_SIZE + DB_MAX_OVERFLOW`(기본 15)개를 엽니다. 끊긴 연결은 꺼내기 전에 확인해 버리고, 30분이 지난 연결은 새로 엽니다 |

직접 들어가 보기:

```bash
docker compose exec db psql -U pawpath -d pawpath
```

## 구조 변경(Alembic)

구조는 `backend/alembic/versions`의 리비전으로 관리합니다. 서버가 켜질 때 최신 리비전까지 자동으로 올리고, PostgreSQL은 구조 변경도 트랜잭션 안에서 일어나 리비전 하나가 실패하면 그 리비전 전체가 되돌아갑니다.

```bash
cd backend
uv run alembic current                                  # 지금 리비전
uv run alembic history                                  # 변경 이력
uv run alembic revision --autogenerate -m "무엇을 바꿈"   # models.py를 고친 뒤 리비전 만들기. 만든 파일을 꼭 읽고 고치세요
uv run alembic upgrade head                             # 적용 (서버를 켜도 적용됨)
uv run alembic downgrade -1                             # 하나 되돌리기
uv run alembic upgrade head --sql                       # 실행하지 않고 SQL만 보기
```

- `0001`은 처음 구조입니다. `downgrade base`까지 되돌리면 모든 테이블과 데이터가 지워지니 빈 DB에서만 쓰세요.
- Alembic 이전에 만든 DB(`alembic_version` 테이블이 없는 SQLite)는 서버가 예전 방식(`app/migrations.py`)으로 0001 구조까지 올린 뒤 0001로 표시하고 이어서 적용합니다. 이때 SQLite면 먼저 `pre-migration-*.db` 백업을 남깁니다.
- 새 컬럼이나 테이블을 `app/migrations.py`의 `ADDED_COLUMNS`에 더하지 마세요. 그 목록은 0001에서 멈췄습니다.
- `tests/test_migrations.py`가 리비전으로 만든 구조와 `models.py`가 같은지 SQLite와 PostgreSQL 양쪽에서 확인합니다. 모델만 고치고 리비전을 만들지 않으면 이 테스트가 실패합니다.

## SQLite 데이터 옮기기

```bash
docker compose up -d --wait
cd backend
uv run python -m app.transfer ./pawpath.db
```

1. 대상(`DATABASE_URL`)이 PostgreSQL이고 비어 있는지 확인합니다. 행이 하나라도 있으면 섞이지 않게 멈춥니다. 서버를 PostgreSQL로 먼저 켰다면 시드가 들어가 있으니 옮긴 뒤에 켜세요.
2. 원본을 `BACKUP_DIR`에 `pre-postgres-*.db`로 백업하고 검증합니다. 원본 파일은 읽기만 하고 바꾸지 않습니다.
3. 백업의 사본을 지금 구조로 올립니다. 예전 구조라면 계정마다 대표 프로필이 생기므로 `profiles`의 수가 원본보다 많게 나옵니다.
4. SQLite가 검사하지 않던 것을 확인합니다. 부모가 없는 외래 키, 글자 수 제한을 넘는 값이 있으면 어느 테이블인지 알리고 멈춥니다.
5. 외래 키 순서대로 옮기고, 번호 시퀀스를 가장 큰 번호로 맞춥니다. 지워서 빈 번호도 그대로 둡니다.
6. 모든 테이블의 모든 행을 기본 키 순서로 하나씩 비교합니다. 누락, 중복, 값이 다른 행이 있으면 멈춥니다.

2~6에서 하나라도 실패하면 대상 DB에 데이터가 남지 않습니다(구조만 남음). 원인을 고친 뒤 다시 실행하면 됩니다.

## 백업과 복구

자동 백업(`app.backup`)은 SQLite만 다룹니다. PostgreSQL은 `pg_dump`로 백업합니다. 백업 파일에는 비밀번호 해시, 경로, 사진이 들어 있으니 주인만 읽게 두세요.

```bash
# 백업 (사용자 지정 형식, 압축됨)
(umask 077 && docker compose exec -T db pg_dump -U pawpath -d pawpath -Fc > backend/backups/pawpath-$(date +%Y%m%d-%H%M%S).dump)

# 새 DB로 복구해 확인한 뒤 바꿔 쓰기
docker compose exec -T db createdb -U pawpath pawpath_restore
docker compose exec -T db pg_restore -U pawpath -d pawpath_restore --no-owner --exit-on-error < backend/backups/파일이름.dump
docker compose exec db psql -U pawpath -d pawpath_restore -c "select count(*) from users"
```

확인이 끝나면 서버를 멈추고 `DATABASE_URL`의 DB 이름을 `pawpath_restore`로 바꾸거나, 지금 DB를 지우고 이름을 바꿉니다. 복구한 뒤에는 [백업 및 복구 정책](BACKUP.md)의 "복구하면 달라지는 것"(세션 끝내기, 공유 비공개, `deletions.jsonl` 재적용)을 직접 처리해야 합니다. SQLite의 `restore` 명령처럼 자동으로 해 주지 않습니다.

## 테스트

```bash
cd backend
uv run pytest                                                                 # SQLite (기본, 빠름)
TEST_DATABASE_URL=postgresql+psycopg://pawpath:비밀번호@localhost:5432/pawpath_test uv run pytest   # PostgreSQL

# 브라우저 E2E를 PostgreSQL로. 빈 DB에서 시작해야 하므로 먼저 비웁니다(테스트 DB만!)
docker compose exec -T db psql -U pawpath -d pawpath_test -c "drop schema public cascade; create schema public authorization pawpath;"
(cd frontend && E2E_DATABASE_URL=postgresql+psycopg://pawpath:비밀번호@localhost:5432/pawpath_test npm run test:e2e)
```

`TEST_DATABASE_URL`, `E2E_DATABASE_URL`에 개발 DB(`pawpath`)를 넣지 마세요. 테스트가 테이블을 지웁니다.

## SQLite와 다른 점

| 항목 | SQLite | PostgreSQL |
|---|---|---|
| 외래 키 | 검사하지 않음 | 항상 검사. 탈퇴는 가리키는 쪽부터 지우는 순서로 이미 맞춰져 있음 |
| 글자 수 제한 | 검사하지 않음 | `VARCHAR(n)`을 넘으면 거부 |
| 번호 | 가장 큰 번호 다음을 씀 | 시퀀스. 번호를 직접 넣으면 시퀀스를 맞춰야 함(`sync_id_sequence`) |
| 지운 행 | `secure_delete`로 파일에서 0으로 덮음 | VACUUM 전까지 데이터 파일에 남고 WAL에도 남음. 아래 한계 참고 |
| 자동 백업 | 서버가 함 | 배포 서버는 `scripts/backup_postgres.sh`를 cron으로. 개발 DB는 `pg_dump`를 직접 |

## 한계

- 탈퇴한 보호자의 데이터가 지운 직후 디스크에서 사라지는지는 보장하지 않습니다. PostgreSQL은 지운 행을 VACUUM이 공간을 재사용할 때까지 데이터 파일에 남기고, WAL 파일에도 남습니다. SQLite에서 확인하던 "파일에 남지 않음" 테스트는 PostgreSQL에서 건너뜁니다.
- 자동 백업과 보존 기간 정리는 배포 서버의 cron(`scripts/backup_postgres.sh`)만 합니다. 복구 뒤 처리(`deletions.jsonl` 재적용 등)는 자동화하지 않았습니다.
- 배포 서버에 실제 데이터를 옮기는 일은 하지 않았습니다. 배포 서버의 DB는 `compose.prod.yaml`로 띄우고, 데이터 이전 절차는 [배포](DEPLOY.md#처음-배포하기-sqlite-데이터가-있을-때)를 따르면 됩니다.
- 백엔드는 컨테이너로 띄우지 않습니다. `docker compose`는 DB만 띄우고, 백엔드는 지금처럼 `./dev.sh` 또는 `uv run uvicorn`으로 띄웁니다.
