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
    url = f"{API}?token={token}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    log.debug("GET %s headers=%s", url, headers)
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        log.error("the partner API refused %s: %s", url, e)
        raise


def main():
    with open(TOKEN_FILE, encoding="utf-8") as f:
        token = f.read().strip()
    log.info("syncing with %s as %s", API, token)
    orders = fetch(token)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(orders, f, indent=2)
    log.info("wrote %d orders", len(orders))
    return 0


if __name__ == "__main__":
    sys.exit(main())
