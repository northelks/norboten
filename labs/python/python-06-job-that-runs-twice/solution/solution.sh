#!/bin/sh
set -eu
cat > /opt/pricing/rebuild.py <<'PY'
#!/usr/bin/env python3
"""Rebuild the shop's price list from the catalogue."""

import fcntl
import json
import os
import sys
import tempfile
import time

CATALOGUE = os.environ.get("PRICING_CATALOGUE", "/srv/pricing/catalogue.json")
OUT = os.environ.get("PRICING_OUT", "/var/lib/pricing/prices.json")
LOCK = os.environ.get("PRICING_LOCK", "/run/pricing-rebuild.lock")
PER_PRODUCT_SECONDS = float(os.environ.get("PRICING_SECONDS_PER_PRODUCT", "0.4"))


def price_of(product):
    time.sleep(PER_PRODUCT_SECONDS)  # the pricing service answers when it answers
    return round(product["cost"] * 1.4, 2)


def take_lock():
    """An advisory lock held for as long as this process lives; the kernel releases it if we die."""
    fd = os.open(LOCK, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd  # keep it open: closing it would release the lock


def write_atomically(path, prices):
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".prices-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(prices, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)  # readers see the old file or the new one, never half of one
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main():
    lock = take_lock()
    if lock is None:
        print(f"rebuild: another rebuild holds {LOCK}", file=sys.stderr)
        return 1
    with open(CATALOGUE, encoding="utf-8") as f:
        catalogue = json.load(f)
    prices = {product["sku"]: price_of(product) for product in catalogue}
    write_atomically(OUT, prices)
    print(f"rebuilt {len(prices)} prices")
    return 0


if __name__ == "__main__":
    sys.exit(main())
PY
systemctl start pricing-rebuild.service
