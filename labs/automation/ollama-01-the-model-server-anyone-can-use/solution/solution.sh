#!/bin/sh
# Reference solution: Ollama back on loopback, only the chat page as an extra origin; nginx asks for
# the team's password.
set -eu
cat > /etc/systemd/system/ollama.service.d/override.conf <<'CONF'
[Service]
Environment="OLLAMA_HOST=127.0.0.1:11434"
Environment="OLLAMA_ORIGINS=https://chat.internal.example"
CONF
systemctl daemon-reload
systemctl restart ollama

printf 'team:%s\n' "$(openssl passwd -apr1 -stdin < /root/team-password)" > /etc/nginx/models.htpasswd
chown root:www-data /etc/nginx/models.htpasswd
chmod 640 /etc/nginx/models.htpasswd
cat > /etc/nginx/conf.d/models.conf <<'CONF'
server {
    listen 8080;
    server_name _;

    auth_basic "models";
    auth_basic_user_file /etc/nginx/models.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:11434;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_read_timeout 600s;
    }
}
CONF
nginx -t
systemctl restart nginx
