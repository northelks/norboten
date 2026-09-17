import os
import pwd
import shlex
import shutil
import tempfile


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        docs, backups = os.path.join(base, "docs"), os.path.join(base, "backups")
        ctx.write(os.path.join(docs, "readable.txt"), "fine\n")
        ctx.write(os.path.join(docs, "private", "salaries.csv"), "secret\n")
        ctx.write(os.path.join(docs, "zz-last.txt"), "also fine\n")
        os.makedirs(backups)
        os.chmod(base, 0o755)
        uid = pwd.getpwnam(ctx.learner).pw_uid
        for root, dirs, files in os.walk(base):
            for name in [root, *(os.path.join(root, n) for n in dirs + files)]:
                os.chown(name, uid, -1)
        os.chmod(os.path.join(docs, "private", "salaries.csv"), 0)  # the learner cannot read it
        cmd = (
            f"cd {shlex.quote(base)} && DOCS_DIR={shlex.quote(docs)} "
            f"BACKUP_DIR={shlex.quote(backups)} /usr/local/bin/backup-docs"
        )
        r = ctx.run(cmd, user=ctx.learner, timeout=25)
        days = sorted(os.listdir(backups))
        dest = os.path.join(backups, days[0]) if len(days) == 1 else backups
        evidence = f"exit {r.code}\nstdout: {r.out!r}\nstderr: {r.err!r}\nbackups: {days}"
        if r.code == 0:
            return ctx.failed(
                "A file that could not be copied still ends in exit status 0.", evidence
            )
        if "salaries.csv" not in r.err:
            return ctx.failed("Standard error does not name the file that failed.", evidence)
        others = [ctx.read(os.path.join(dest, n)) for n in ("readable.txt", "zz-last.txt")]
        if others != ["fine\n", "also fine\n"]:
            return ctx.failed("One unreadable file stopped the other files being copied.", evidence)
        return ctx.passed(
            "The failed file is named, the rest are copied, the exit is non-zero.", evidence
        )
    finally:
        shutil.rmtree(base, ignore_errors=True)
