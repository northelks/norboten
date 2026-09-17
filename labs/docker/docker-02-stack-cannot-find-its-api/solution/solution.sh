#!/bin/sh
set -eu
cd /srv/shop
cat > compose.yaml <<'YAML'
name: shop

services:
  web:
    image: nginx:1.29-alpine
    restart: unless-stopped
    ports:
      - "8088:80"
    volumes:
      - ./web/default.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on:
      - api

  api:
    image: nginx:1.29-alpine
    restart: unless-stopped
    volumes:
      - ./api/default.conf:/etc/nginx/conf.d/default.conf:ro
      - ./api/status.json:/srv/api/status.json:ro
YAML
sed -i 's#proxy_pass http://localhost:8089/;#proxy_pass http://api:80/;#' web/default.conf
docker compose up -d --remove-orphans
for i in $(seq 1 20); do
    curl -fs http://127.0.0.1:8088/api/status.json >/dev/null && break
    sleep 1
done
