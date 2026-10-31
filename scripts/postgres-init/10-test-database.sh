#!/usr/bin/env bash
# 볼륨을 처음 만들 때 한 번만 돈다. 테스트가 테이블을 지우고 다시 만드는 DB를 개발 DB와 따로 둔다.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -c "CREATE DATABASE ${POSTGRES_DB}_test OWNER \"$POSTGRES_USER\""
