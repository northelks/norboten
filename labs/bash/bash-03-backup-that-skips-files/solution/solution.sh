#!/bin/sh
set -eu
cat > /usr/local/bin/backup-docs <<'SCRIPT'
#!/bin/bash
# backup-docs — copy every document into today's backup directory
set -uo pipefail

DOCS_DIR=${DOCS_DIR:-/srv/docs}
BACKUP_DIR=${BACKUP_DIR:-/var/backups/docs}
dest="$BACKUP_DIR/$(date +%F)"

mkdir -p -- "$dest" || exit 1
count=0
failed=0
# NUL-separated names, read in this shell (not a pipeline's subshell), so any name survives and the
# counters are still there after the loop
while IFS= read -r -d '' f; do
    rel=${f#"$DOCS_DIR"/}
    if mkdir -p -- "$dest/$(dirname -- "$rel")" && cp -p -- "$f" "$dest/$rel"; then
        count=$((count + 1))
    else
        echo "backup-docs: could not copy $rel" >&2
        failed=$((failed + 1))
    fi
done < <(find "$DOCS_DIR" -type f -print0)

echo "backed up $count files"
[ "$failed" -eq 0 ]
SCRIPT
chmod 755 /usr/local/bin/backup-docs
systemctl start backup-docs.service
