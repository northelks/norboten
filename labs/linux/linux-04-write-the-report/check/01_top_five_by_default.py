import collections
import os
import random
import tempfile

SCRIPT = "/usr/local/bin/top-talkers"


def _log(counts, rng):
    lines = [
        f'{ip} - - [11/Sep/2026:10:00:00 +0000] "GET / HTTP/1.1" 200 1'
        for ip, n in counts.items()
        for _ in range(n)
    ]
    rng.shuffle(lines)
    return "\n".join(lines) + "\n"


def _expected(counts, n):
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    return [f"{c} {ip}" for ip, c in ranked]


def check(ctx):
    if not os.access(SCRIPT, os.X_OK):
        return ctx.failed(f"{SCRIPT} does not exist or is not executable.")
    rng = random.Random(1)
    counts = collections.OrderedDict(
        (f"10.{rng.randint(0, 9)}.{rng.randint(0, 250)}.{rng.randint(1, 250)}", rng.randint(1, 60))
        for _ in range(12)
    )
    with tempfile.NamedTemporaryFile("w", prefix=".norboten-probe-", delete=False) as f:
        f.write(_log(counts, rng))
    try:
        r = ctx.run([SCRIPT, f.name])
    finally:
        os.unlink(f.name)
    want = _expected(counts, 5)
    got = r.out.strip().splitlines()
    evidence = "expected:\n" + "\n".join(want) + "\n\ngot:\n" + r.text
    if r.code != 0 or got != want:
        return ctx.failed(
            "The default report (top 5) is not what the specification asks for.", evidence
        )
    return ctx.passed("The default report lists the top 5 correctly.")
