import os
import shutil
import tempfile

LINES = [
    '10.0.0.1 - - [16/Sep/2026:02:00:00 +0000] "GET / HTTP/1.1" 200 5120',
    '10.0.0.2 - - [16/Sep/2026:02:00:01 +0000] "GET /cart HTTP/1.1" 200 500',
    '10.0.0.3 - - [16/Sep/2026:02:00:02 +0000] "POST /pay HTTP/1.1" 302 0',
]


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        log, report = os.path.join(base, "access.log"), os.path.join(base, "errors.txt")
        ctx.write(log, "\n".join(LINES) + "\n")
        r = ctx.run(["errors-report"], env={"LOG": log, "REPORT": report}, timeout=20)
        text = ctx.read(report)
        evidence = f"a log with no 5xx\nexit {r.code}\n{r.text}\nreport: {text!r}"
        if r.code != 0:
            return ctx.failed("A night with no server errors makes the script fail.", evidence)
        if (text or "").split() != ["total", "0"]:
            return ctx.failed("A night with no server errors does not report 'total 0'.", evidence)
        return ctx.passed("A quiet night is reported as total 0.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
