#!/bin/sh
# deploy.sh <api-tag> — roll the server to a new API image, and back if it does not come up.
#
# Run on the server in /opt/norboten, by the deploy workflow over SSH (or by hand). It pulls the
# image, restarts only what changed, waits for /readyz, and on failure puts the previous tag back
# and restarts that. The tag in use is kept in .deployed; the one before it in .deployed.previous.
set -eu
cd "$(dirname "$0")"

tag=${1:?usage: deploy.sh <api-tag>}
previous=$(cat .deployed 2>/dev/null || echo latest)
compose="docker compose --env-file .env"

set_tag() { sed -i.bak "s/^API_TAG=.*/API_TAG=$1/" .env && rm -f .env.bak; }

# A changed Caddyfile is a file inside a bind mount: compose compares services, not file contents,
# so `up -d` leaves the container running and the new configuration is never read. Validate it in
# the container that will serve it, then reload — graceful, no dropped connection.
reload_caddy() {
    if ! $compose exec -T caddy caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile \
        >/dev/null 2>&1; then
        echo "the Caddyfile on the server does not validate — the running config stays" >&2
        return 1
    fi
    $compose exec -T caddy caddy reload --adapter caddyfile --config /etc/caddy/Caddyfile
}

ready() {
    for _ in $(seq 1 60); do
        if $compose exec -T api python -c \
            "import httpx; httpx.get('http://127.0.0.1:8000/readyz').raise_for_status()" \
            >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
    done
    return 1
}

echo "deploying api:$tag (previous: $previous)"
set_tag "$tag"
# every image, but one failed pull must not abort the others: the rehearsal VM's API image is
# loaded by hand rather than pulled, and that is fine as long as it is there
$compose pull --ignore-pull-failures
docker image inspect "$(grep '^API_IMAGE=' .env | cut -d= -f2):$tag" >/dev/null \
    || { echo "api image $tag is neither pullable nor present" >&2; exit 1; }
$compose up -d --remove-orphans
if ready; then
    echo "$previous" > .deployed.previous
    echo "$tag" > .deployed
    docker image prune -f >/dev/null
    reload_caddy || exit 1
    echo "api:$tag is ready"
    exit 0
fi

echo "api:$tag did not become ready — rolling back to api:$previous" >&2
$compose logs --tail 50 api >&2 || true
set_tag "$previous"
$compose up -d api
ready && echo "rolled back to api:$previous" >&2
exit 1
