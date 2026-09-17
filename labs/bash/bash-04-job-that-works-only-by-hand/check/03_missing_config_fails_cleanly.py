import os
import shutil
import tempfile

SCRIPT = "/opt/reports/bin/nightly-report"
PREVIOUS = "Disk use per project, yesterday\n/srv/projects/alpha   300 KiB\n"


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        out = os.path.join(base, "report.txt")
        ctx.write(out, PREVIOUS)
        conf = os.path.join(base, "no-such.conf")
        r = ctx.run(
            ["sh", "-c", 'cd / && exec "$@"', "sh", "env", f"REPORT_CONF={conf}",
             f"REPORT_OUT={out}", SCRIPT],
            timeout=25,
        )  # fmt: skip
        after = ctx.read(out)
        evidence = f"REPORT_CONF={conf}\nexit {r.code}\n{r.text}\nreport now: {after!r}"
        if r.code == 0:
            return ctx.failed("A missing configuration is reported as success.", evidence)
        if after != PREVIOUS:
            return ctx.failed("A missing configuration replaced the previous report.", evidence)
        return ctx.passed("A missing configuration fails and keeps the last report.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
