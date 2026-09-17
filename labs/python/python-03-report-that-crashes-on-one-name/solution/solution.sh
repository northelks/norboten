#!/bin/sh
set -eu
cat > /opt/members/report.py <<'PY'
#!/usr/bin/env python3
"""Members per city, from every export in the members directory."""

import csv
import os
import tempfile
from collections import Counter

MEMBERS = os.environ.get("MEMBERS_DIR", "/srv/members")
OUT = os.environ.get("SUMMARY_OUT", "/var/lib/members/summary.csv")


def encoding_of(name):
    """The old Windows tool writes cp1252 and says so in the file name (/srv/members/README)."""
    return "cp1252" if name.endswith(".cp1252.csv") else "utf-8"


def rows(path, encoding):
    # strict by default: a file that does not decode is an error, not a name with holes in it
    with open(path, newline="", encoding=encoding) as f:
        yield from csv.DictReader(f)


def main():
    cities = Counter()
    names = []
    for name in sorted(os.listdir(MEMBERS)):
        if not name.endswith(".csv"):
            continue
        for row in rows(os.path.join(MEMBERS, name), encoding_of(name)):
            cities[row["city"]] += 1
            names.append(row["name"])

    directory = os.path.dirname(OUT) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".summary-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["city", "members"])
            for city, count in sorted(cities.items()):
                writer.writerow([city, count])
            writer.writerow(["names", " ".join(names)])
        os.chmod(tmp, 0o644)
        os.replace(tmp, OUT)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    print(f"summary written: {len(cities)} cities, {len(names)} members")


main()
PY
systemctl start members-report.service
