import os
import tempfile

SCRIPT = "/usr/local/bin/top-talkers"


def check(ctx):
    if not os.access(SCRIPT, os.X_OK):
        return ctx.failed(f"{SCRIPT} does not exist or is not executable.")
    missing = "/nonexistent/.norboten-probe-access.log"
    r = ctx.run([SCRIPT, missing])
    if r.code != 1 or f"top-talkers: cannot read {missing}" not in r.err:
        return ctx.failed(
            "A missing file is not reported as specified.", f"exit {r.code}\nstderr: {r.err}"
        )
    with tempfile.NamedTemporaryFile("w", prefix=".norboten-probe-", delete=False) as f:
        f.write("# nothing but a comment\n\n")
    try:
        r = ctx.run([SCRIPT, f.name])
    finally:
        os.unlink(f.name)
    if r.code != 0 or r.out.strip() or r.err.strip():
        return ctx.failed(
            "A log with no requests should print nothing and exit 0.",
            f"exit {r.code}\nstdout: {r.out}\nstderr: {r.err}",
        )
    return ctx.passed("Missing files and empty logs are handled as specified.")
