import os
import tempfile

SCRIPT = "/usr/local/bin/top-talkers"
# ties on purpose; byte order puts 10.0.0.10 before 10.0.0.9
COUNTS = {"10.0.0.9": 4, "10.0.0.10": 4, "172.16.0.1": 7, "10.0.0.2": 4, "192.168.1.1": 1}


def check(ctx):
    if not os.access(SCRIPT, os.X_OK):
        return ctx.failed(f"{SCRIPT} does not exist or is not executable.")
    lines = [f'{ip} - - [x] "GET / HTTP/1.1" 200 1' for ip, n in COUNTS.items() for _ in range(n)]
    with tempfile.NamedTemporaryFile("w", prefix=".norboten-probe-", delete=False) as f:
        f.write("\n".join(reversed(lines)) + "\n")
    try:
        r = ctx.run([SCRIPT, "-n", "3", f.name])
        r_all = ctx.run([SCRIPT, "-n", "10", f.name])
    finally:
        os.unlink(f.name)
    want3 = ["7 172.16.0.1", "4 10.0.0.10", "4 10.0.0.2"]
    want_all = [*want3, "4 10.0.0.9", "1 192.168.1.1"]
    if r.out.strip().splitlines() != want3:
        return ctx.failed(
            "-n 3 with tied counts is not ordered as specified.",
            "expected:\n" + "\n".join(want3) + "\n\ngot:\n" + r.text,
        )
    if r_all.out.strip().splitlines() != want_all:
        return ctx.failed(
            "Asking for more rows than there are addresses gives the wrong output.",
            "expected:\n" + "\n".join(want_all) + "\n\ngot:\n" + r_all.text,
        )
    return ctx.passed("-n and tie-breaking follow the specification.")
