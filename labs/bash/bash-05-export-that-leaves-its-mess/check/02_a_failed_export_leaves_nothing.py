import os
import pwd
import shlex
import shutil
import tempfile


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        src, dest, tmp = (os.path.join(base, n) for n in ("src", "dest", "tmp"))
        ctx.write(os.path.join(src, "a.csv"), "id,sku,qty\n1,A,1\n")
        ctx.write(os.path.join(src, "b.csv"), "id,sku,qty\n2,B,2\n")
        ctx.write(os.path.join(dest, "orders-2026-01-01.csv.gz"), "yesterday")
        os.makedirs(tmp)
        os.chmod(base, 0o755)
        uid = pwd.getpwnam(ctx.learner).pw_uid
        for root, dirs, files in os.walk(base):
            for n in [root, *(os.path.join(root, x) for x in dirs + files)]:
                os.chown(n, uid, -1)
        os.chmod(os.path.join(src, "b.csv"), 0)  # unreadable for the learner
        q = shlex.quote
        cmd = (
            f"cd {q(base)} && TMPDIR={q(tmp)} EXPORT_SRC={q(src)} EXPORT_DEST={q(dest)} "
            "export-orders"
        )
        r = ctx.run(cmd, user=ctx.learner, timeout=25)
        made = sorted(os.listdir(dest))
        left = sorted(os.listdir(tmp))
        evidence = f"exit {r.code}\n{r.text}\ndestination: {made}\ntemporary directory: {left}"
        if r.code == 0:
            return ctx.failed("An unreadable order file still ends in exit status 0.", evidence)
        if made != ["orders-2026-01-01.csv.gz"]:
            return ctx.failed("A failed export left a file in the destination.", evidence)
        if left:
            return ctx.failed("A failed export left a temporary file behind.", evidence)
        if ctx.read(os.path.join(dest, "orders-2026-01-01.csv.gz")) != "yesterday":
            return ctx.failed("A failed export changed an earlier export.", evidence)
        return ctx.passed("A failed export fails and leaves nothing behind.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
