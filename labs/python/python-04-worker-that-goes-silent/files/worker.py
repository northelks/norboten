#!/usr/bin/env python3
"""Ingest each file dropped into the queue, one row per file."""

import json
import os
import time

QUEUE = os.environ.get("INGEST_QUEUE", "/srv/ingest/queue")
LEDGER = os.environ.get("INGEST_LEDGER", "/var/lib/ingest/ledger.csv")
STATE = os.environ.get("INGEST_STATE", "/var/lib/ingest/done.json")
WORK_SECONDS = float(os.environ.get("INGEST_WORK_SECONDS", "1.0"))


def load_done():
    try:
        with open(STATE) as f:
            return set(json.load(f))
    except (OSError, ValueError):
        return set()


def save_done(done):
    with open(STATE, "w") as f:
        json.dump(sorted(done), f)


def ingest(name):
    with open(os.path.join(QUEUE, name)) as f:
        amount = f.read().strip()
    with open(LEDGER, "a") as ledger:
        ledger.write(f"{name},")
        ledger.flush()
        time.sleep(WORK_SECONDS)  # the slow part: the accounting system answers when it answers
        ledger.write(f"{amount}\n")


def main():
    done = load_done()
    while True:
        for name in sorted(os.listdir(QUEUE)):
            if name in done:
                continue
            ingest(name)
            done.add(name)
            save_done(done)
            print(f"ingested {name}")
        time.sleep(0.5)


main()
