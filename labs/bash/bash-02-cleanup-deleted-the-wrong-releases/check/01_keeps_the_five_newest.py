import os
import shutil
import tempfile
import time

# run from inside the probe directory, so nothing the script does lands anywhere else
IN_PROBE = ["sh", "-c", 'cd "$1" && exec /usr/local/bin/prune-releases', "prune"]
NAMES = [f"202607{d:02d}-120000" for d in range(1, 9)]


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        rel = os.path.join(base, "releases")
        now = time.time()
        for i, name in enumerate(NAMES):
            ctx.write(os.path.join(rel, name, "VERSION"), name)
            os.utime(
                os.path.join(rel, name), (now - i * 60, now - i * 60)
            )  # oldest name, newest mtime
        os.symlink(os.path.join(rel, NAMES[-1]), os.path.join(rel, "current"))
        ctx.write(os.path.join(rel, "README.txt"), "not a release\n")
        r = ctx.run([*IN_PROBE, base], env={"RELEASES_DIR": rel}, timeout=20)
        left = sorted(os.listdir(rel))
        want = sorted([*NAMES[3:], "README.txt", "current"])
        evidence = f"exit {r.code}\n{r.text}\nleft: {left}\nexpected: {want}"
        if left != want:
            return ctx.failed("The releases left are not the five newest by name.", evidence)
        if not os.path.exists(os.path.join(rel, "current", "VERSION")):
            return ctx.failed("current no longer leads to a release.", evidence)
        if r.code != 0:
            return ctx.failed("The cleanup did the right thing but exited non-zero.", evidence)
        return ctx.passed("The five newest releases by name are kept.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
