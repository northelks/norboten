#!/bin/sh
set -eu

# an account for the job: no home to log in from, no shell, no password
id partner-sync >/dev/null 2>&1 || \
    useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin partner-sync
passwd -l partner-sync >/dev/null 2>&1 || true

# the token: readable by that account and nobody else
chown partner-sync:partner-sync /etc/partner/token
chmod 600 /etc/partner/token
chmod 755 /etc/partner
chown -R partner-sync:partner-sync /var/lib/partner

cat > /opt/partner/sync.py <<'PY'
#!/usr/bin/env python3
"""Fetch the partner's orders for today."""

import json
import logging
import os
import sys
import urllib.error
import urllib.request

API = os.environ.get("PARTNER_API", "http://127.0.0.1:8977/orders")
TOKEN_FILE = os.environ.get("PARTNER_TOKEN_FILE", "/etc/partner/token")
OUT = os.environ.get("PARTNER_OUT", "/var/lib/partner/orders.json")
LEVEL = os.environ.get("PARTNER_LOG_LEVEL", "INFO")

logging.basicConfig(level=LEVEL, format="%(levelname)s %(message)s", stream=sys.stdout)
log = logging.getLogger("partner-sync")


def fetch(token):
    # the token travels in the header only, so no URL — logged, stored or in an error — carries it
    request = urllib.request.Request(API, headers={"Authorization": f"Bearer {token}"})
    log.debug("GET %s", API)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        log.error("the partner API refused the request: HTTP %s", e.code)
        raise SystemExit(1) from None


def main():
    with open(TOKEN_FILE, encoding="utf-8") as f:
        token = f.read().strip()
    log.info("syncing with %s", API)
    orders = fetch(token)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(orders, f, indent=2)
    log.info("wrote %d orders", len(orders))
    return 0


if __name__ == "__main__":
    sys.exit(main())
PY

mkdir -p /etc/systemd/system/partner-sync.service.d
cat > /etc/systemd/system/partner-sync.service.d/user.conf <<'UNIT'
[Service]
User=partner-sync
Group=partner-sync
UNIT
systemctl daemon-reload
systemctl restart partner-sync.service
