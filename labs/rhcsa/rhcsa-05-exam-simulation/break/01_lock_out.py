"""Root password unknown, the learner's sudo gone, GRUB waits long enough to interrupt."""

import os
import re
import secrets


def apply(ctx):
    ctx.run(["chpasswd"], input=f"root:{secrets.token_urlsafe(24)}\n", check=True)
    for path in ("/etc/sudoers.d/90-cloud-init-users",):
        if os.path.exists(path):
            os.unlink(path)
    ctx.run(["gpasswd", "-d", ctx.learner, "wheel"])
    grub = ctx.read("/etc/default/grub") or ""
    ctx.write(
        "/etc/default/grub", re.sub(r"^GRUB_TIMEOUT=.*$", "GRUB_TIMEOUT=10", grub, flags=re.M)
    )
    ctx.run(["grub2-mkconfig", "-o", "/boot/grub2/grub.cfg"], check=True)
