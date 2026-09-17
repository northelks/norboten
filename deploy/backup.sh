#!/bin/sh
# backup.sh — dump the database, prove the dump restores, keep two weeks here, optionally off-box.
#
# A backup nobody has restored is a rumour: every run restores what it just dumped into a scratch
# database and counts the rows of the tables that matter before it keeps anything. Run nightly by
# norboten-backup.timer. Restoring for real is restore.sh.
set -eu
cd "$(dirname "$0")"
. ./.env

dir=${BACKUP_DIR:-/var/backups/norboten}
keep=${BACKUP_KEEP_DAYS:-14}
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$dir"
compose="docker compose --env-file .env"
psql() { $compose exec -T postgres psql -v ON_ERROR_STOP=1 -U norboten "$@"; }

out="$dir/norboten-$stamp.dump"
$compose exec -T postgres pg_dump -U norboten -Fc norboten > "$out"

psql -q -c "DROP DATABASE IF EXISTS restore_check" postgres
psql -q -c "CREATE DATABASE restore_check" postgres
$compose exec -T postgres pg_restore -U norboten -d restore_check --no-owner < "$out"
counts=$(psql -tA -d restore_check -c \
    "SELECT (SELECT count(*) FROM users) || ' users, ' || (SELECT count(*) FROM attempts) || ' attempts'")
echo "norboten: restore check passed — $counts"
psql -q -c "DROP DATABASE restore_check" postgres

find "$dir" -name '*.dump' -mtime +"$keep" -delete

if [ -n "${BACKUP_TARGET:-}" ]; then
    RESTIC_REPOSITORY=$BACKUP_TARGET RESTIC_PASSWORD=$RESTIC_PASSWORD restic backup --quiet "$dir"
    RESTIC_REPOSITORY=$BACKUP_TARGET RESTIC_PASSWORD=$RESTIC_PASSWORD \
        restic forget --quiet --keep-daily 14 --keep-weekly 8 --prune
    echo "copied off-box to $BACKUP_TARGET"
fi
