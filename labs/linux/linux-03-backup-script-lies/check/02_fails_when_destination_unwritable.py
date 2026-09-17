import os
import shutil
import tempfile


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        src, log = os.path.join(base, "src"), os.path.join(base, "log")
        ctx.write(os.path.join(src, "file.txt"), "x\n")
        dest = os.path.join(base, "not-a-directory")
        ctx.write(dest, "")  # a file where the destination directory should be
        r = ctx.run(
            ["/usr/local/bin/backup-data"],
            env={"BACKUP_SRC": src, "BACKUP_DEST": dest, "BACKUP_LOG": log},
        )
        logged = ctx.read(log) or ""
        evidence = f"exit {r.code}\nstderr: {r.err.strip()}\nlog: {logged.strip()}"
        if r.code == 0:
            return ctx.failed(
                "The archive could not be written, and the script exited 0.", evidence
            )
        if "backup OK" in logged:
            return ctx.failed("The script logged 'backup OK' for a backup that failed.", evidence)
        if not r.err.strip():
            return ctx.failed("The script failed silently: nothing on stderr.", evidence)
        return ctx.passed("An unwritable destination makes the script fail loudly.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
