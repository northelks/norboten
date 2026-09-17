import os
import pwd
import shutil
import signal
import subprocess
import tempfile
import time


def as_user(name):
    """Run the child as that user, in a process group of its own — how systemd stops a unit is
    a signal to every process in it, and that is what this check sends."""
    entry = pwd.getpwnam(name)

    def drop():
        os.setgid(entry.pw_gid)
        os.initgroups(name, entry.pw_gid)
        os.setuid(entry.pw_uid)

    return drop


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        src, dest, tmp = (os.path.join(base, n) for n in ("src", "dest", "tmp"))
        ctx.write(os.path.join(src, "a.csv"), "id,sku,qty\n1,A,1\n")
        os.makedirs(dest)
        os.makedirs(tmp)
        os.mkfifo(os.path.join(src, "b.csv"))  # reading it blocks: the export is mid-way
        os.chmod(base, 0o755)
        uid = pwd.getpwnam(ctx.learner).pw_uid
        for root, dirs, files in os.walk(base):
            for n in [root, *(os.path.join(root, x) for x in dirs + files)]:
                os.chown(n, uid, -1)
        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "LC_ALL": "C",
            "HOME": pwd.getpwnam(ctx.learner).pw_dir,
            "TMPDIR": tmp,
            "EXPORT_SRC": src,
            "EXPORT_DEST": dest,
        }
        proc = subprocess.Popen(
            ["/usr/local/bin/export-orders"],
            cwd=base,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
            preexec_fn=as_user(ctx.learner),
        )
        time.sleep(2)
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            out, _ = proc.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            out, _ = proc.communicate(timeout=5)
            return ctx.failed("The export did not stop within 8 seconds of SIGTERM.", out)
        time.sleep(0.5)
        made, left = sorted(os.listdir(dest)), sorted(os.listdir(tmp))
        shared = os.path.exists("/tmp/export.tmp")
        evidence = (
            f"SIGTERM to the process group after 2 s\nexit {proc.returncode}\n{out}\n"
            f"destination: {made}\ntemporary directory: {left}\n/tmp/export.tmp exists: {shared}"
        )
        if proc.returncode == 0:
            return ctx.failed("An interrupted export exits 0.", evidence)
        if made:
            return ctx.failed("An interrupted export left a file in the destination.", evidence)
        if left or shared:
            return ctx.failed("An interrupted export left a temporary file behind.", evidence)
        return ctx.passed("An interrupted export stops and leaves nothing behind.", evidence)
    finally:
        if os.path.exists("/tmp/export.tmp") and os.stat("/tmp/export.tmp").st_uid != 0:
            os.unlink("/tmp/export.tmp")
        shutil.rmtree(base, ignore_errors=True)
