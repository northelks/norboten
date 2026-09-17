#!/usr/bin/env python3
"""Members per city, from every export in the members directory."""

import csv
import os
from collections import Counter

MEMBERS = os.environ.get("MEMBERS_DIR", "/srv/members")
OUT = os.environ.get("SUMMARY_OUT", "/var/lib/members/summary.csv")


def rows(path):
    with open(path, newline="") as f:
        yield from csv.DictReader(f)


def main():
    cities = Counter()
    names = []
    for name in sorted(os.listdir(MEMBERS)):
        if not name.endswith(".csv"):
            continue
        for row in rows(os.path.join(MEMBERS, name)):
            cities[row["city"]] += 1
            names.append(row["name"])
    with open(OUT, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["city", "members"])
        for city, count in sorted(cities.items()):
            writer.writerow([city, count])
        writer.writerow(["names", " ".join(names)])
    print(f"summary written: {len(cities)} cities, {len(names)} members")


main()
