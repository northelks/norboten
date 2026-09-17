import gzip
import os
import pwd
import shlex
import shutil
import subprocess
import tempfile
import time


def _rows(path):
    with gzip.open(path, "rt") as f:
        return f.read().splitlines()


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    fifo = os.path.join(base, "a", "src", "z.csv")
    try:
        for run in ("a", "b"):
            os.makedirs(os.path.join(base, run, "dest"))
            os.makedirs(os.path.join(base, run, "tmp"))
        ctx.write(os.path.join(base, "a", "src", "a1.csv"), "id,sku,qty\n1,A,1\n")
        os.mkfifo(fifo)  # run a waits here while run b does all its work
        ctx.write(os.path.join(base, "b", "src", "b1.csv"), "id,sku,qty\n2,B,2\n3,B,3\n")
        os.chmod(base, 0o755)
        uid = pwd.getpwnam(ctx.learner).pw_uid
        for root, dirs, files in os.walk(base):
            for n in [root, *(os.path.join(root, x) for x in dirs + files)]:
                os.chown(n, uid, -1)

        def command(run):
            d = os.path.join(base, run)
            q = shlex.quote
            return (
                f"cd {q(d)} && TMPDIR={q(d + '/tmp')} EXPORT_SRC={q(d + '/src')} "
                f"EXPORT_DEST={q(d + '/dest')} export-orders"
            )

        a = subprocess.Popen(
            ["su", "-s", "/bin/sh", "-c", command("a"), ctx.learner],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True,
        )  # fmt: skip
        time.sleep(1.5)
        rb = ctx.run(command("b"), user=ctx.learner, timeout=20)
        with open(fifo, "w") as f:  # now let run a finish
            f.write("id,sku,qty\n9,Z,9\n")
        try:
            out_a, _ = a.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            a.kill()
            return ctx.failed("The first of two exports never finished.")
        files = {run: sorted(os.listdir(os.path.join(base, run, "dest"))) for run in ("a", "b")}
        evidence = f"a: exit {a.returncode} {out_a}\nb: exit {rb.code} {rb.text}\n{files}"
        if a.returncode or rb.code or len(files["a"]) != 1 or len(files["b"]) != 1:
            return ctx.failed("Two exports at the same time did not both succeed.", evidence)
        rows_a = _rows(os.path.join(base, "a", "dest", files["a"][0]))
        rows_b = _rows(os.path.join(base, "b", "dest", files["b"][0]))
        evidence += f"\nexport a: {rows_a}\nexport b: {rows_b}"
        if rows_a != ["id,sku,qty", "1,A,1", "9,Z,9"] or rows_b != ["id,sku,qty", "2,B,2", "3,B,3"]:
            return ctx.failed("Two exports at the same time mixed up or lost rows.", evidence)
        return ctx.passed(
            "Two exports at the same time each wrote their own complete file.", evidence
        )
    finally:
        if os.path.exists("/tmp/export.tmp") and os.stat("/tmp/export.tmp").st_uid != 0:
            os.unlink("/tmp/export.tmp")
        shutil.rmtree(base, ignore_errors=True)
