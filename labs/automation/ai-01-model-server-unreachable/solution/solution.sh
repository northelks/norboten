#!/bin/sh
set -eu
chown -R ollama:ollama /srv/models
chmod 755 /srv/models
systemctl enable --now ollama

cat > /etc/nginx/conf.d/model-proxy.conf <<'CONF'
server {
    listen 8080;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:11434;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_read_timeout 600s;
    }
}
CONF
systemctl enable nginx
nginx -t
systemctl reload nginx
