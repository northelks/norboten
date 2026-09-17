#!/bin/sh
set -eu
# the helper keeps its job; only its name changes, so that it cannot stand in for the standard
# library module of the same name when Python searches the program's own directory first
mv /opt/digest/calendar.py /opt/digest/office_calendar.py
rm -rf /opt/digest/__pycache__
cat > /opt/digest/digest.py <<'PY'
#!/usr/bin/env python3
"""One line about today's events, for the morning mail."""

import calendar
import datetime
import json
import os

import office_calendar

EVENTS = os.environ.get("DIGEST_EVENTS", "/srv/digest/events.json")
OUT = os.environ.get("DIGEST_OUT", "/var/lib/digest/today.txt")


def main():
    with open(EVENTS, encoding="utf-8") as f:
        events = json.load(f)
    today = datetime.date.today()
    days = calendar.monthrange(today.year, today.month)[1]
    open_days = sum(
        1
        for day in range(1, days + 1)
        if office_calendar.is_open(datetime.date(today.year, today.month, day).strftime("%a"))
    )
    line = f"{today.isoformat()}: {len(events)} events, {days} days in the month, {open_days} open\n"
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(line)
    print(line.strip())


main()
PY
systemctl restart digest.service
