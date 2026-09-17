import re


def check(ctx):
    fstab = ctx.read("/etc/fstab") or ""
    raw = [ln for ln in fstab.splitlines() if re.match(r"^\s*/dev/(vd|sd|nvme|xvd)", ln)]
    app = [ln for ln in fstab.splitlines() if re.search(r"\s/var/lib/app\s", ln)]
    if raw:
        return ctx.failed("fstab mounts a filesystem by a raw device name.", "\n".join(raw))
    if not app or not re.match(r"^\s*(UUID|LABEL)=", app[0]):
        return ctx.failed("/var/lib/app is not mounted by UUID or label.", "\n".join(app))
    return ctx.passed("Every filesystem is mounted by UUID or label.", fstab)
