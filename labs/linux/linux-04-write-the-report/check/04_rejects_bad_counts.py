import os
import tempfile

SCRIPT = "/usr/local/bin/top-talkers"


def check(ctx):
    if not os.access(SCRIPT, os.X_OK):
        return ctx.failed(f"{SCRIPT} does not exist or is not executable.")
    with tempfile.NamedTemporaryFile("w", prefix=".norboten-probe-", delete=False) as f:
        f.write('10.0.0.1 - - [x] "GET / HTTP/1.1" 200 1\n')
    try:
        for bad in ("0", "-3", "abc", "2.5", ""):
            r = ctx.run([SCRIPT, "-n", bad, f.name])
            if r.code != 2 or "top-talkers: invalid count" not in r.err or r.out.strip():
                return ctx.failed(
                    f"-n {bad!r} is not rejected as specified.",
                    f"exit {r.code}\nstdout: {r.out}\nstderr: {r.err}",
                )
    finally:
        os.unlink(f.name)
    return ctx.passed("Invalid counts are rejected with status 2 and the right message.")
