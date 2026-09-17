import os
import shutil
import tempfile


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        report = os.path.join(base, "errors.txt")
        log = os.path.join(base, "rotated-away.log")
        r = ctx.run(["errors-report"], env={"LOG": log, "REPORT": report}, timeout=20)
        evidence = f"LOG={log} (missing)\nexit {r.code}\nstdout: {r.out!r}\nstderr: {r.err!r}"
        if r.code == 0:
            return ctx.failed("A missing log is reported as success.", evidence)
        if not r.err.strip():
            return ctx.failed("A missing log fails with nothing on standard error.", evidence)
        return ctx.passed("A missing log is an error, and says so.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
