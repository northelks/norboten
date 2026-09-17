#!/bin/sh
set -eu
mkdir -p /var/lib/jobs-redis
# SAVE writes a snapshot even when automatic saving is off
docker exec jobs-redis redis-cli save
docker cp jobs-redis:/data/dump.rdb /var/lib/jobs-redis/dump.rdb
mkdir -p /etc/systemd/system/jobs-redis.service.d
cat > /etc/systemd/system/jobs-redis.service.d/persistent.conf <<'UNIT'
[Service]
ExecStart=
ExecStart=/usr/bin/docker run --rm --name jobs-redis -p 127.0.0.1:6379:6379 -v /var/lib/jobs-redis:/data redis:7.4-alpine redis-server
UNIT
systemctl daemon-reload
systemctl restart jobs-redis.service
for i in $(seq 1 30); do
    [ "$(docker exec jobs-redis redis-cli ping 2>/dev/null)" = PONG ] && break
    sleep 1
done
