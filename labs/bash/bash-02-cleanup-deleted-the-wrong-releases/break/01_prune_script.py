"""The mtime-ordered, word-splitting prune script, real releases, and a timer pointing elsewhere."""

import os
import shutil
import time

RELEASES = [
    "20260801-120000",
    "20260830-090000 rollback",
    "20260905-140000",
    "20260908-101500",
    "20260910-163000",
    "20260911-180000 hotfix",
    "20260912-083000",
    "20260913-101500",
]


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    shutil.copy(os.path.join(files, "prune-releases"), "/usr/local/bin/prune-releases")
    os.chmod("/usr/local/bin/prune-releases", 0o755)
    base = "/srv/app/releases"
    now = time.time()
    for i, name in enumerate(RELEASES):
        ctx.write(os.path.join(base, name, "VERSION"), name + "\n")
        # restored from a backup: the oldest releases carry the newest timestamps
        stamp = now - i * 3600
        os.utime(os.path.join(base, name), (stamp, stamp))
    if not os.path.islink(os.path.join(base, "current")):
        os.symlink(os.path.join(base, RELEASES[-1]), os.path.join(base, "current"))
    for unit in ("prune-releases.service", "prune-releases.timer"):
        shutil.copy(os.path.join(files, unit), f"/etc/systemd/system/{unit}")
    ctx.run(["systemctl", "daemon-reload"], check=True)
