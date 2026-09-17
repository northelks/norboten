#!/bin/sh
# Reference solution: a policy logrotate will read, that runs as the directory's owner, keeps a
# week compressed and gives the new log back to shop — then rotate the big log now.
set -eu
cat > /etc/logrotate.d/shop <<'CONF'
/var/log/shop/*.log {
    su shop shop
    size 50M
    rotate 7
    compress
    missingok
    create 0640 shop shop
}
CONF
chmod 0644 /etc/logrotate.d/shop
logrotate /etc/logrotate.conf
