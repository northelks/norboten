#!/bin/sh
set -eu
cat > /usr/local/bin/errors-report <<'SCRIPT'
#!/bin/bash
# errors-report — server errors per endpoint, for the morning stand-up
set -euo pipefail

LOG=${LOG:-/var/log/shop/access.log}
REPORT=${REPORT:-/var/lib/shop/errors.txt}

if [ ! -r "$LOG" ]; then
    echo "errors-report: cannot read $LOG" >&2
    exit 1
fi

tmp=$(mktemp "$REPORT.XXXXXX")
trap 'rm -f -- "$tmp"' EXIT

# awk exits 0 whether or not a line matched: "no errors" is an answer, not a failure
awk '$9 ~ /^5[0-9][0-9]$/ { print $7 }' "$LOG" | sort | uniq -c | sort -k1,1nr -k2,2 |
    awk '{ print $1, $2; total += $1 } END { print "total", total + 0 }' > "$tmp"
chmod 644 "$tmp"
mv -f -- "$tmp" "$REPORT"
trap - EXIT
SCRIPT
chmod 755 /usr/local/bin/errors-report
systemctl start errors-report.service
