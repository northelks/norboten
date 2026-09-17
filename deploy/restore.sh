#!/bin/sh
# restore.sh <norboten-dump> — put a backup back. Stops the API while it works.
set -eu
cd "$(dirname "$0")"
dump=${1:?usage: restore.sh /var/backups/norboten/norboten-<stamp>.dump}
compose="docker compose --env-file .env"

$compose stop api
$compose exec -T postgres pg_restore -U norboten -d norboten --clean --if-exists --no-owner < "$dump"
$compose start api
echo "restored $dump"
