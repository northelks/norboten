"""/dev/vdb is ext4, mounted at /var/log/app by UUID in fstab."""

import os


def apply(ctx):
    dev = "/dev/vdb"
    if not ctx.run(["blkid", dev]).ok:
        ctx.run(["mkfs.ext4", "-q", "-L", "applogs", dev], check=True)
    uuid = ctx.run(["blkid", "-s", "UUID", "-o", "value", dev], check=True).out.strip()
    os.makedirs("/var/log/app", exist_ok=True)
    fstab = ctx.read("/etc/fstab") or ""
    if "/var/log/app" not in fstab:
        ctx.write(
            "/etc/fstab", fstab.rstrip("\n") + f"\nUUID={uuid} /var/log/app ext4 defaults 0 2\n"
        )
    if not os.path.ismount("/var/log/app"):
        ctx.run(["mount", "/var/log/app"], check=True)
