#!/bin/sh
set -eu
cat > /opt/sync/sync.py <<'PY'
#!/usr/bin/env python3
"""Copy the records from the inventory API into a JSON file other services read."""

import http.client
import json
import os
import sys
import tempfile
import urllib.request

API = os.environ.get("SYNC_API", "http://127.0.0.1:8901/records")
OUTPUT = os.environ.get("SYNC_OUTPUT", "/var/lib/sync/records.json")
TIMEOUT = 10


def fetch():
    # urlopen raises HTTPError for 4xx and 5xx answers, URLError when nothing answers
    with urllib.request.urlopen(API, timeout=TIMEOUT) as response:
        records = json.load(response)
    if not isinstance(records, list):
        raise ValueError("the API did not return a list")
    return records


def write_atomically(path, records):
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".records-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(records, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main():
    try:
        records = fetch()
    except (OSError, ValueError, http.client.HTTPException) as e:
        print(f"sync: {API}: {e}", file=sys.stderr)
        return 1
    write_atomically(OUTPUT, records)
    print(f"done: {len(records)} records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
PY
sed -i 's#^SYNC_API=.*#SYNC_API=http://127.0.0.1:8901/records#' /etc/sync/sync.env
systemctl start sync.service
