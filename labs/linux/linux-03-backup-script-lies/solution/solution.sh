#!/bin/sh
set -eu
cat > /usr/local/bin/backup-data <<'SCRIPT'
#!/bin/bash
# backup-data — nightly archive of the data directory.
# BACKUP_SRC, BACKUP_DEST and BACKUP_LOG override the defaults.
set -euo pipefail
SRC=${BACKUP_SRC:-/srv/data}
DEST=${BACKUP_DEST:-/var/backups}
LOG=${BACKUP_LOG:-/var/log/backup-data.log}
ARCHIVE="$DEST/data-$(date +%Y%m%d-%H%M%S).tar.gz"

log() { echo "$(date -Is) $*" >> "$LOG"; }
fail() { echo "backup-data: $*" >&2; log "backup FAILED: $*"; exit 1; }

[ -d "$SRC" ] || fail "source $SRC does not exist"
tar -czf "$ARCHIVE" -C "$SRC" . || fail "could not write $ARCHIVE"
log "backup OK: $ARCHIVE"
SCRIPT
chmod 755 /usr/local/bin/backup-data
if [ -f /etc/cron.d/backup-data ]; then
    sed -i 's#root backup-data#root /usr/local/bin/backup-data#' /etc/cron.d/backup-data
else
    sed -i 's#\* backup-data$#* /usr/local/bin/backup-data#' /etc/crontabs/root
fi
