import os
import shutil
import tempfile

IN_PROBE = ["sh", "-c", 'cd "$1" && exec /usr/local/bin/prune-releases', "prune"]
NAMES = [
    "20260701-120000 old build",
    "20260702-120000",
    "20260703-120000  two spaces",
    "20260704-120000",
    "20260705-120000 kept label",
    "20260706-120000",
    "20260707-120000",
    "20260708-120000 newest",
]


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        rel = os.path.join(base, "releases")
        for name in NAMES:
            ctx.write(os.path.join(rel, name, "VERSION"), name)
        for decoy in ("old", "build", "two", "spaces"):  # what the pieces of the names would hit
            ctx.write(os.path.join(rel, decoy), "decoy\n")
        r = ctx.run([*IN_PROBE, base], env={"RELEASES_DIR": rel}, timeout=20)
        left = sorted(os.listdir(rel))
        want = sorted([*NAMES[3:], "old", "build", "two", "spaces"])
        evidence = f"exit {r.code}\n{r.text}\nleft: {left}\nexpected: {want}"
        if left != want:
            return ctx.failed("Releases with spaces in their names were mishandled.", evidence)
        return ctx.passed("Names with spaces are kept or deleted as releases.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
