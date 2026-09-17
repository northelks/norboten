import os
import pwd
import shlex
import shutil
import tempfile

NAMES = {
    "Contract - ACME.pdf": "contract\n",
    "sub dir/deep/notes.md": "deep\n",
    "-rf.txt": "leading dash\n",
    "  two blanks.txt": "leading blanks\n",
    "back\\slash.txt": "backslash\n",
    "line\nbreak.txt": "newline\n",
}


def _probe(ctx, base):
    uid = pwd.getpwnam(ctx.learner).pw_uid
    for root, dirs, files in os.walk(base):
        for name in [root, *(os.path.join(root, n) for n in dirs + files)]:
            os.chown(name, uid, -1)


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        docs, backups = os.path.join(base, "docs"), os.path.join(base, "backups")
        for rel, text in NAMES.items():
            ctx.write(os.path.join(docs, rel), text)
        os.makedirs(backups)
        os.chmod(base, 0o755)
        _probe(ctx, base)
        cmd = (
            f"cd {shlex.quote(base)} && DOCS_DIR={shlex.quote(docs)} "
            f"BACKUP_DIR={shlex.quote(backups)} /usr/local/bin/backup-docs"
        )
        r = ctx.run(cmd, user=ctx.learner, timeout=25)
        days = sorted(os.listdir(backups))
        evidence = f"exit {r.code}\n{r.text}\nbackup directories: {days}"
        if len(days) != 1:
            return ctx.failed("The backup did not create one directory for today.", evidence)
        dest = os.path.join(backups, days[0])
        missing = [rel for rel, text in NAMES.items() if ctx.read(os.path.join(dest, rel)) != text]
        copied = sorted(
            os.path.relpath(os.path.join(root, f), dest)
            for root, _, files in os.walk(dest)
            for f in files
        )
        evidence += f"\ncopied: {copied}"
        if missing:
            return ctx.failed(
                f"{len(missing)} of {len(NAMES)} files are missing or different in the backup.",
                evidence + f"\nmissing: {missing}",
            )
        stray = sorted(set(copied) - set(NAMES))
        if stray:
            return ctx.failed("The backup holds files that are not in the source.", evidence)
        return ctx.passed("Every file was copied, whatever its name.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
