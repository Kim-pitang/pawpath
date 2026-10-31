#!/usr/bin/env bash
# 배포 DB(compose.prod.yaml의 db)를 pg_dump로 백업하고, 보존 기간이 지난 백업을 지운다. cron에서 하루 한 번 부른다.
#   30 4 * * * /home1/ncloud/pawpath/scripts/backup_postgres.sh >> /home1/ncloud/pawpath-backups/backup.log 2>&1
# 복구 방법은 docs/POSTGRES.md의 "백업과 복구"에 있다.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIR="${PG_BACKUP_DIR:-$HOME/pawpath-backups}"
DAYS="${PG_BACKUP_RETENTION_DAYS:-14}"
compose() { sudo -n docker compose -f "$ROOT/compose.prod.yaml" --project-directory "$ROOT" "$@"; }

# 비밀번호 해시, 경로, 사진이 들어 있어 주인만 읽게 한다.
umask 077
mkdir -p "$DIR"
FILE="$DIR/pawpath-$(date +%Y%m%d-%H%M%S).dump"
compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$FILE.tmp"
# 잘리거나 비어 있는 파일은 백업으로 남기지 않는다. 목록을 읽을 수 있어야 복구할 수 있다.
compose exec -T db pg_restore --list < "$FILE.tmp" > /dev/null
mv "$FILE.tmp" "$FILE"
find "$DIR" -maxdepth 1 -name 'pawpath-*.dump' -mtime +"$DAYS" -print -delete
echo "$(date '+%F %T') 백업함: $FILE ($(du -h "$FILE" | cut -f1))"
