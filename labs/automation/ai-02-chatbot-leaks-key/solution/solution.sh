#!/bin/sh
set -eu
# 1-2: the key lives in one private file, and not in the unit
chown chatgw:chatgw /etc/chat-gateway/upstream.key
chmod 600 /etc/chat-gateway/upstream.key
sed -i '/^Environment=UPSTREAM_KEY=/d' /etc/systemd/system/chat-gateway.service
# 3 and 5: require a client token, stop logging headers
sed -i 's/^REQUIRE_TOKEN=.*/REQUIRE_TOKEN=1/; s/^LOG_HEADERS=.*/LOG_HEADERS=0/' \
    /etc/chat-gateway/gateway.env
systemctl daemon-reload
systemctl restart chat-gateway

# 4: rate limit at the proxy
cat > /etc/nginx/conf.d/chat-limit.conf <<'CONF'
limit_req_zone $binary_remote_addr zone=chatgw:10m rate=2r/s;
CONF
cat > /etc/nginx/conf.d/chat-proxy.conf <<'CONF'
server {
    listen 8090;
    server_name _;

    location / {
        limit_req zone=chatgw burst=5 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:8100;
        proxy_set_header Authorization $http_authorization;
    }
}
CONF
systemctl enable nginx
nginx -t
systemctl reload nginx
