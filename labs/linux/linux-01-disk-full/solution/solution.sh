#!/bin/sh
set -eu
rm -rf /var/log/app/archive
cat > /etc/logrotate.d/ledger <<'CONF'
/var/log/app/*.log {
    size 20M
    rotate 4
    compress
    missingok
    notifempty
    copytruncate
}
CONF
# restarting ledger closes the deleted file and opens a fresh log
if command -v systemctl >/dev/null 2>&1; then
    systemctl restart ledger
else
    rc-service ledger restart
fi
