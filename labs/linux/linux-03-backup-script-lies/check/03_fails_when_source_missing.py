import os
import shutil
import tempfile


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        dest, log = os.path.join(base, "dest"), os.path.join(base, "log")
        os.makedirs(dest)
        r = ctx.run(
            ["/usr/local/bin/backup-data"],
            env={
                "BACKUP_SRC": os.path.join(base, "no-such-dir"),
                "BACKUP_DEST": dest,
                "BACKUP_LOG": log,
            },
        )
        logged = ctx.read(log) or ""
        evidence = f"exit {r.code}\nstderr: {r.err.strip()}\nlog: {logged.strip()}"
        if r.code == 0:
            return ctx.failed("The source did not exist, and the script exited 0.", evidence)
        if "backup OK" in logged:
            return ctx.failed("The script logged 'backup OK' with no source to back up.", evidence)
        if not r.err.strip():
            return ctx.failed("The script failed silently: nothing on stderr.", evidence)
        return ctx.passed("A missing source makes the script fail loudly.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
