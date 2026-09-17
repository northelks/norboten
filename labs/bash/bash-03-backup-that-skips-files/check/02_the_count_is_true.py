import os
import pwd
import shlex
import shutil
import tempfile

NAMES = ["a.txt", "b c.txt", "d/e.txt", "d/f g/h.txt", "i.txt"]


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        docs, backups = os.path.join(base, "docs"), os.path.join(base, "backups")
        for rel in NAMES:
            ctx.write(os.path.join(docs, rel), rel + "\n")
        os.makedirs(backups)
        os.chmod(base, 0o755)
        uid = pwd.getpwnam(ctx.learner).pw_uid
        for root, dirs, files in os.walk(base):
            for name in [root, *(os.path.join(root, n) for n in dirs + files)]:
                os.chown(name, uid, -1)
        cmd = (
            f"cd {shlex.quote(base)} && DOCS_DIR={shlex.quote(docs)} "
            f"BACKUP_DIR={shlex.quote(backups)} /usr/local/bin/backup-docs"
        )
        r = ctx.run(cmd, user=ctx.learner, timeout=25)
        lines = [line for line in r.out.splitlines() if line.strip()]
        last = lines[-1] if lines else ""
        evidence = f"exit {r.code}\nstdout: {r.out!r}\nstderr: {r.err!r}"
        if r.code != 0:
            return ctx.failed("Five readable files did not back up cleanly.", evidence)
        if last != f"backed up {len(NAMES)} files":
            return ctx.failed(
                f"After copying {len(NAMES)} files the script reports: {last!r}.", evidence
            )
        return ctx.passed(f"The script reports the {len(NAMES)} files it copied.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
