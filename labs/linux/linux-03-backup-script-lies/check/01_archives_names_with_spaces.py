import os
import shutil
import tarfile
import tempfile

FIXTURE = {
    "plain.txt": "a\n",
    "with space.txt": "b\n",
    "dir with spaces/inner file.log": "c\n",
    "deep/er/still.txt": "d\n",
    "several   spaces.txt": "e\n",  # not a leading space: "./ name" would split into "./"
}


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        src, dest = os.path.join(base, "src"), os.path.join(base, "dest")
        os.makedirs(dest)
        for name, text in FIXTURE.items():
            ctx.write(os.path.join(src, name), text)
        env = {"BACKUP_SRC": src, "BACKUP_DEST": dest, "BACKUP_LOG": os.path.join(base, "log")}
        r = ctx.run(["/usr/local/bin/backup-data"], env=env)
        archives = [f for f in os.listdir(dest) if f.endswith((".tar.gz", ".tgz", ".tar"))]
        if not archives:
            return ctx.failed("No archive was written.", r.text)
        with tarfile.open(os.path.join(dest, archives[0])) as tar:
            names = {os.path.normpath(m.name) for m in tar.getmembers() if m.isfile()}
        missing = [n for n in FIXTURE if os.path.normpath(n) not in names]
        if missing:
            message = f"{len(missing)} of {len(FIXTURE)} files are missing from the archive."
            return ctx.failed(message, "missing: " + ", ".join(repr(m) for m in missing))
        return ctx.passed("Every file made it into the archive, spaces and all.")
    finally:
        shutil.rmtree(base, ignore_errors=True)
