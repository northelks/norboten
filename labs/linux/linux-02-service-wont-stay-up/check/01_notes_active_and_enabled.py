def check(ctx):
    enabled = ctx.service_enabled("notes")
    active = ctx.service_active("notes")
    status = ctx.run(["systemctl", "status", "--no-pager", "-n", "5", "notes"]).text
    if not enabled:
        return ctx.failed("notes is not set to start at boot.", status)
    if not active:
        return ctx.failed("notes is not running.", status)
    return ctx.passed("notes is running and enabled at boot.", status)
