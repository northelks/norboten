def check(ctx):
    status = ctx.run(["systemctl", "status", "--no-pager", "-n", "8", "myapp.service"]).text
    if not ctx.service_enabled("myapp.service"):
        return ctx.failed("myapp.service is not enabled.", status)
    if not ctx.service_active("myapp.service"):
        return ctx.failed("myapp.service is not running.", status)
    log = ctx.run(["journalctl", "-u", "myapp.service", "-b", "-n", "20", "--no-pager"]).text
    if "logged in" not in log:
        return ctx.failed("myapp has not logged in to the database since this boot.", log)
    return ctx.passed("myapp started and logged in with the rotated password.", log)
