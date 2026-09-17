import calendar
import datetime
import json
import os
import re
import shutil
import tempfile

EVENTS = [{"at": "09:10", "what": "a"}, {"at": "11:40", "what": "b"}]
OPEN = ("Mon", "Tue", "Wed", "Thu", "Fri")


def expected_line(count):
    today = datetime.date.today()
    days = calendar.monthrange(today.year, today.month)[1]
    open_days = sum(
        1
        for d in range(1, days + 1)
        if datetime.date(today.year, today.month, d).strftime("%a") in OPEN
    )
    return f"{today.isoformat()}: {count} events, {days} days in the month, {open_days} open"


def run(ctx, cwd, base):
    events = os.path.join(base, "events.json")
    out = os.path.join(base, "today.txt")
    ctx.write(events, json.dumps(EVENTS))
    r = ctx.run(
        [
            "sh",
            "-c",
            'cd "$1" && shift && exec "$@"',
            "sh",
            cwd,
            "python3",
            "/opt/digest/digest.py",
        ],
        env={"DIGEST_EVENTS": events, "DIGEST_OUT": out},
        timeout=25,
    )
    return r, (ctx.read(out) or "").strip()


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        r, line = run(ctx, "/opt/digest", base)
        want = expected_line(len(EVENTS))
        evidence = f"cwd /opt/digest\nexit {r.code}\n{r.text}\ndigest: {line!r}\nexpected: {want!r}"
        if r.code != 0:
            return ctx.failed("Started from its own directory, the digest fails.", evidence)
        if not re.fullmatch(re.escape(want), line):
            return ctx.failed("The digest line is not what the office asked for.", evidence)
        return ctx.passed("From its own directory the digest is written.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
