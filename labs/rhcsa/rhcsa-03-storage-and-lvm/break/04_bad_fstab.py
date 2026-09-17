"""The 3 a.m. fix: the /var/lib/app entry now names a device that does not exist."""

import re


def apply(ctx):
    fstab = ctx.read("/etc/fstab") or ""
    fstab = re.sub(r"^UUID=\S+(\s+/var/lib/app\s)", r"/dev/vdb1\1", fstab, flags=re.M)
    ctx.write("/etc/fstab", fstab)
    ctx.run(["systemctl", "daemon-reload"], check=True)
