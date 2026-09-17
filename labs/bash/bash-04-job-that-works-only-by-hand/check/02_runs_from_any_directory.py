import os
import shutil
import tempfile

SCRIPT = "/opt/reports/bin/nightly-report"


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        out = os.path.join(base, "report.txt")
        path = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
        r = ctx.run(
            ["sh", "-c", 'cd "$1" && shift && exec "$@"', "sh", base,
             "env", "-i", f"PATH={path}", f"REPORT_OUT={out}", SCRIPT],
            timeout=25,
        )  # fmt: skip
        report = ctx.read(out) or ""
        evidence = f"cd {base}; REPORT_OUT=… {SCRIPT}\nexit {r.code}\n{r.text}\n{report}"
        if r.code != 0:
            return ctx.failed("Started outside /opt/reports, the script fails.", evidence)
        if "/srv/projects/alpha" not in report or "/srv/projects/beta" not in report:
            return ctx.failed(
                "Started outside /opt/reports, the report does not list the configured projects.",
                evidence,
            )
        return ctx.passed("From any directory the script finds its configuration.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
