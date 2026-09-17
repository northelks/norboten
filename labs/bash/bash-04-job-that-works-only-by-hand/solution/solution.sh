#!/bin/sh
set -eu
cat > /opt/reports/bin/nightly-report <<'SCRIPT'
#!/bin/bash
# nightly-report — disk use per project, for the morning mail
set -euo pipefail

# everything this script needs, named here: not the caller's PATH, not the caller's directory
PATH=/opt/reports/tools/bin:/usr/sbin:/usr/bin:/sbin:/bin
conf=${REPORT_CONF:-/opt/reports/report.conf}
out=${REPORT_OUT:-/var/lib/reports/latest.txt}

if [ ! -r "$conf" ]; then
    echo "nightly-report: cannot read $conf" >&2
    exit 1
fi
. "$conf"

tmp=$(mktemp "$out.XXXXXX")
trap 'rm -f -- "$tmp"' EXIT
{
    echo "Disk use per project, $(date +%F)"
    for project in $projects; do
        du -sk -- "$project" | report-fmt
    done
} > "$tmp"
chmod 644 "$tmp"
mv -f -- "$tmp" "$out"
trap - EXIT
echo "report written to $out"
SCRIPT
chmod 755 /opt/reports/bin/nightly-report
systemctl start nightly-report.service
