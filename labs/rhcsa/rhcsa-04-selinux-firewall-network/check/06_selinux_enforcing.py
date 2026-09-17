import re


def check(ctx):
    mode = ctx.run(["getenforce"]).out.strip()
    config = ctx.read("/etc/selinux/config") or ""
    m = re.search(r"^SELINUX=(\w+)", config, re.M)
    configured = m.group(1) if m else "?"
    evidence = f"getenforce: {mode}\n/etc/selinux/config: SELINUX={configured}"
    if mode != "Enforcing" or configured != "enforcing":
        return ctx.failed("SELinux is not enforcing. Turning it off is not a fix.", evidence)
    return ctx.passed("SELinux is enforcing, now and at boot.", evidence)
