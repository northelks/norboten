#!/usr/bin/env python3
"""Copy the records from the inventory API into a JSON file other services read."""

import json
import os
import urllib.request

API = os.environ.get("SYNC_API", "http://127.0.0.1:8901/records")
OUTPUT = os.environ.get("SYNC_OUTPUT", "/var/lib/sync/records.json")


def fetch():
    try:
        with urllib.request.urlopen(API) as response:
            return json.load(response)
    except Exception as e:
        print(f"warning: {e}")
        return []


def main():
    records = fetch()
    with open(OUTPUT, "w") as f:
        json.dump(records, f, indent=2)
    print(f"done: {len(records)} records")


main()
