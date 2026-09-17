import os
import shutil
import tempfile

SCRIPT = "/opt/reports/bin/nightly-report"


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        for name, size in (("one", 20_000), ("two", 40_000)):
            ctx.write(os.path.join(base, "projects", name, "f"), "y" * size)
        conf = os.path.join(base, "report.conf")
        ctx.write(conf, f'projects="{base}/projects/one {base}/projects/two"\n')
        out = os.path.join(base, "report.txt")
        cmd = ["env", "-i", f"REPORT_CONF={conf}", f"REPORT_OUT={out}", SCRIPT]
        r = ctx.run(["sh", "-c", 'cd / && exec "$@"', "sh", *cmd], timeout=25)
        report = ctx.read(out) or ""
        evidence = f"env -i REPORT_CONF=… REPORT_OUT=… {SCRIPT}\nexit {r.code}\n{r.text}\n{report}"
        if r.code != 0:
            return ctx.failed("With an empty environment the script fails.", evidence)
        lines = report.splitlines()
        rows = [line for line in lines if line.startswith(f"{base}/projects/")]
        if len(rows) != 2 or not all(line.rstrip().endswith("KiB") for line in rows):
            return ctx.failed(
                "With an empty environment the report does not list both projects.", evidence
            )
        return ctx.passed("With an empty environment the report is complete.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
