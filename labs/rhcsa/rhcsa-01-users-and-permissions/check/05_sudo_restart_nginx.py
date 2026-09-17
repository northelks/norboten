def check(ctx):
    cmd = ["sudo", "-l", "-U", "kmorris", "/usr/bin/systemctl", "restart", "nginx"]
    r = ctx.run(cmd)
    listing = ctx.run(["sudo", "-l", "-U", "kmorris"]).text
    if not r.ok:
        return ctx.failed("sudo does not allow kmorris to restart nginx.", listing)
    return ctx.passed("kmorris may restart nginx with sudo.", listing)
