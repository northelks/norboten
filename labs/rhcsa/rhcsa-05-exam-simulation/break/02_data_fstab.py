"""/dev/vdb is XFS; fstab mounts /data by a UUID that no longer exists."""

import os
import uuid


def apply(ctx):
    if not ctx.run(["blkid", "/dev/vdb"]).ok:
        ctx.run(["mkfs.xfs", "-q", "/dev/vdb"], check=True)
    os.makedirs("/data", exist_ok=True)
    fstab = ctx.read("/etc/fstab") or ""
    if " /data " not in fstab:
        entry = f"UUID={uuid.uuid4()} /data xfs defaults,x-systemd.device-timeout=10s 0 0"
        ctx.write("/etc/fstab", fstab.rstrip("\n") + "\n" + entry + "\n")
        ctx.run(["systemctl", "daemon-reload"], check=True)
