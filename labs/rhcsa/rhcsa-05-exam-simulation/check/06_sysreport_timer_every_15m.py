import re


def check(ctx):
    if not ctx.service_enabled("sysreport.timer"):
        return ctx.failed("sysreport.timer does not start at boot.")
    if not ctx.service_active("sysreport.timer"):
        return ctx.failed("sysreport.timer is not active.")
    show = ctx.run(
        ["systemctl", "show", "sysreport.timer", "-p", "TimersCalendar", "-p", "TimersMonotonic"]
    ).out
    every_15 = (
        re.search(r"OnCalendar=[^;]*\*:0?0/15", show)
        or re.search(r"OnCalendar=[^;]*\*:0?0,15,30,45", show)
        or re.search(r"OnUnitActiveUSec=15min\b", show)
    )
    if not every_15:
        return ctx.failed("The timer has no schedule that runs every 15 minutes.", show)
    return ctx.passed("sysreport.timer runs every 15 minutes and starts at boot.", show)
