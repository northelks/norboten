#!/bin/sh
set -eu
cat > /opt/ingest/worker.py <<'PY'
#!/usr/bin/env python3
"""Ingest each file dropped into the queue, one row per file."""

import json
import os
import signal
import sys
import tempfile
import time

QUEUE = os.environ.get("INGEST_QUEUE", "/srv/ingest/queue")
LEDGER = os.environ.get("INGEST_LEDGER", "/var/lib/ingest/ledger.csv")
STATE = os.environ.get("INGEST_STATE", "/var/lib/ingest/done.json")
WORK_SECONDS = float(os.environ.get("INGEST_WORK_SECONDS", "1.0"))

# the journal reads a pipe, not a terminal, so Python would buffer 8 KiB at a time
sys.stdout.reconfigure(line_buffering=True)

stopping = False


def stop(signum, frame):
    global stopping
    stopping = True


def load_done():
    try:
        with open(STATE, encoding="utf-8") as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def save_done(done):
    directory = os.path.dirname(STATE) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".done-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(sorted(done), f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, STATE)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def ingest(name):
    with open(os.path.join(QUEUE, name), encoding="utf-8") as f:
        amount = f.read().strip()
    time.sleep(WORK_SECONDS)  # the slow part: the accounting system answers when it answers
    with open(LEDGER, "a", encoding="utf-8") as ledger:  # one write, one complete row
        ledger.write(f"{name},{amount}\n")


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    done = load_done()
    while not stopping:
        for name in sorted(os.listdir(QUEUE)):
            if stopping:
                break
            if name in done:
                continue
            ingest(name)
            done.add(name)
            save_done(done)  # the row is on disk before the file counts as done
            print(f"ingested {name}")
        time.sleep(0.5)
    print("stopping")
    return 0


if __name__ == "__main__":
    sys.exit(main())
PY
systemctl restart ingest.service
