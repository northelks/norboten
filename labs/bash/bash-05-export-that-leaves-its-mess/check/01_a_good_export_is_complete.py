import gzip
import os
import pwd
import shlex
import shutil
import tempfile

FILES = {
    "a.csv": "id,sku,qty\n1,A,1\n2,B,2\n",
    "b late.csv": "id,sku,qty\n3,C,3\n",
    "c.csv": "id,sku,qty\n4,D,4\n5,E,5\n",
}


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        src, dest, tmp = (os.path.join(base, n) for n in ("src", "dest", "tmp"))
        for name, text in FILES.items():
            ctx.write(os.path.join(src, name), text)
        os.makedirs(dest)
        os.makedirs(tmp)
        os.chmod(base, 0o755)
        uid = pwd.getpwnam(ctx.learner).pw_uid
        for root, dirs, files in os.walk(base):
            for n in [root, *(os.path.join(root, x) for x in dirs + files)]:
                os.chown(n, uid, -1)
        q = shlex.quote
        cmd = (
            f"cd {q(base)} && TMPDIR={q(tmp)} EXPORT_SRC={q(src)} EXPORT_DEST={q(dest)} "
            "export-orders"
        )
        r = ctx.run(cmd, user=ctx.learner, timeout=25)
        made = sorted(os.listdir(dest))
        evidence = f"exit {r.code}\n{r.text}\ndestination: {made}"
        if r.code != 0 or len(made) != 1 or not made[0].startswith("orders-"):
            return ctx.failed("A good export did not produce one orders file.", evidence)
        with gzip.open(os.path.join(dest, made[0]), "rt") as f:
            rows = f.read().splitlines()
        evidence += "\n" + "\n".join(rows)
        want = ["1,A,1", "2,B,2", "3,C,3", "4,D,4", "5,E,5"]
        if rows[:1] != ["id,sku,qty"] or sorted(rows[1:]) != want:
            return ctx.failed("The export does not hold one header and every row.", evidence)
        return ctx.passed("A good export holds the header and every row.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
