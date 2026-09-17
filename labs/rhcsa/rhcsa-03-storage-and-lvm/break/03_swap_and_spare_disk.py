"""A swap file exists but is off and gone from fstab; /dev/vdc is an unused PV."""

import os


def apply(ctx):
    if not os.path.exists("/swapfile"):
        ctx.run(
            ["dd", "if=/dev/zero", "of=/swapfile", "bs=1M", "count=256", "status=none"], check=True
        )
        os.chmod("/swapfile", 0o600)
        ctx.run(["mkswap", "-q", "/swapfile"], check=True)
    ctx.run(["swapoff", "-a"])
    fstab = ctx.read("/etc/fstab") or ""
    ctx.write("/etc/fstab", "".join(ln for ln in fstab.splitlines(True) if " swap " not in ln))
    if not ctx.run(["pvs", "/dev/vdc"]).ok:
        ctx.run(["pvcreate", "-y", "/dev/vdc"], check=True)
