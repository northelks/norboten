def check(ctx):
    lines = ctx.run(["systemctl", "list-timers", "--all", "--no-pager", "etl-report.timer"]).out
    if not ctx.service_enabled("etl-report.timer"):
        return ctx.failed("etl-report.timer does not start at boot.", lines)
    if not ctx.service_active("etl-report.timer"):
        return ctx.failed("etl-report.timer is not active.", lines)
    return ctx.passed("The timer is enabled and active.", lines)
