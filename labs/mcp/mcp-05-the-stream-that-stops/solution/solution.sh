#!/bin/sh
# Reference solution: nginx passes the event stream through as it is written and waits long enough
# for a slow step; the server listens on loopback only, so the proxy is the one way in.
set -eu
cat > /etc/nginx/conf.d/reports.conf <<'NGINX'
server {
    listen 127.0.0.1:8080;
    access_log /var/log/nginx/reports.access.log;

    location /mcp {
        proxy_pass http://127.0.0.1:8931;
        proxy_set_header Host $host;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
NGINX
sed -i 's/"bind": "0.0.0.0"/"bind": "127.0.0.1"/' /etc/reports-mcp/config.json
reports-mcp restart
proxy-restart
