import os
import shutil
import tempfile

IN_PROBE = ["sh", "-c", 'cd "$1" && exec /usr/local/bin/prune-releases', "prune"]


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        canaries = [f"important-{i}" for i in range(8)]
        for name in canaries:
            ctx.write(os.path.join(base, name, "data"), "keep me\n")
        missing = os.path.join(base, "moved-away", "releases")
        r = ctx.run([*IN_PROBE, base], env={"RELEASES_DIR": missing}, timeout=20)
        left = sorted(n for n in os.listdir(base) if n.startswith("important-"))
        evidence = f"exit {r.code}\n{r.text}\nleft in the starting directory: {left}"
        if left != canaries:
            return ctx.failed(
                "With its releases directory missing, the script deleted files where it started.",
                evidence,
            )
        if r.code == 0:
            return ctx.failed("With its releases directory missing, the script exits 0.", evidence)
        return ctx.passed(
            "A missing releases directory stops the script before it deletes.", evidence
        )
    finally:
        shutil.rmtree(base, ignore_errors=True)
