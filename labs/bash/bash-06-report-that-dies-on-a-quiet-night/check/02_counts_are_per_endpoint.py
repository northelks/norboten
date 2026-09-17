import os
import shutil
import tempfile

HITS = [
    ("/cart", 502), ("/pay", 500), ("/cart", 200), ("/cart", 502), ("/api/stock", 503),
    ("/pay", 500), ("/products", 200), ("/api/stock", 504), ("/cart", 500), ("/about", 404),
]  # fmt: skip
WANT = [["3", "/cart"], ["2", "/api/stock"], ["2", "/pay"], ["total", "7"]]


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        log, report = os.path.join(base, "access.log"), os.path.join(base, "errors.txt")
        ctx.write(
            log,
            "".join(
                f'10.0.0.9 - - [16/Sep/2026:03:00:{i:02d} +0000] "GET {p} HTTP/1.1" {s} 500\n'
                for i, (p, s) in enumerate(HITS)
            ),
        )
        r = ctx.run(["errors-report"], env={"LOG": log, "REPORT": report}, timeout=20)
        text = ctx.read(report) or ""
        got = [line.split() for line in text.splitlines() if line.strip()]
        evidence = f"exit {r.code}\n{r.text}\nreport:\n{text}\nexpected: {WANT}"
        if r.code != 0:
            return ctx.failed("A log with server errors makes the script fail.", evidence)
        if got != WANT:
            return ctx.failed("The counts per endpoint, or their order, are wrong.", evidence)
        return ctx.passed("One line per endpoint, counted and ordered correctly.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
