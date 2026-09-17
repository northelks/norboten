import re


def check(ctx):
    conf = ctx.read("/etc/chrony.conf") or ""
    sources = [ln.split()[:2] for ln in conf.splitlines() if re.match(r"^\s*(server|pool)\s", ln)]
    if sources != [["server", "192.168.5.2"]]:
        return ctx.failed(
            "chrony is not configured with 192.168.5.2 as its only source.",
            "\n".join(" ".join(s) for s in sources) or "(no sources)",
        )
    if not ctx.service_enabled("chronyd") or not ctx.service_active("chronyd"):
        return ctx.failed("chronyd is not running and enabled.")
    return ctx.passed("chrony uses 192.168.5.2 only.")
