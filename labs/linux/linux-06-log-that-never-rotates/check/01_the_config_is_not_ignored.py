def check(ctx):
    if ctx.read("/etc/logrotate.d/shop") is None:
        return ctx.failed("/etc/logrotate.d/shop is gone: there is no policy for the shop log.")
    r = ctx.run(["logrotate", "-d", "/etc/logrotate.conf"], timeout=60)
    lines = [
        line
        for line in r.text.splitlines()
        if "shop" in line and ("rror" in line or "gnor" in line)
    ]
    if any("Ignoring" in line or "found error in file shop" in line for line in lines):
        return ctx.failed("logrotate ignores /etc/logrotate.d/shop.", "\n".join(lines))
    if "/var/log/shop" not in r.text:
        return ctx.failed(
            "logrotate reads its configuration and never mentions /var/log/shop.", r.text[-1500:]
        )
    return ctx.passed("logrotate reads the shop policy.", "\n".join(lines) or "no errors for shop")
