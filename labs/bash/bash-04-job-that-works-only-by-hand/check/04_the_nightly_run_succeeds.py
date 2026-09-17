import time


def _props(ctx):
    out = ctx.run(
        [
            "systemctl", "show", "nightly-report.service", "-p", "Result", "-p", "ExecMainStatus",
            "-p", "ExecMainExitTimestampMonotonic",
        ]
    ).out  # fmt: skip
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def check(ctx):
    if not (
        ctx.service_enabled("nightly-report.timer") and ctx.service_active("nightly-report.timer")
    ):
        return ctx.failed("nightly-report.timer is not enabled and active.")
    props = _props(ctx)
    deadline = time.monotonic() + 25  # just after a boot, the timer's first run may still be due
    while props.get("ExecMainExitTimestampMonotonic", "0") == "0" and time.monotonic() < deadline:
        time.sleep(2)
        props = _props(ctx)
    log = ctx.run(
        ["journalctl", "-u", "nightly-report.service", "-b", "-n", "12", "--no-pager"]
    ).text
    if props.get("ExecMainExitTimestampMonotonic", "0") == "0":
        return ctx.failed("The timer has not run the report since this boot.", log)
    if props.get("Result") != "success" or props.get("ExecMainStatus") != "0":
        return ctx.failed("The last run started by the timer failed.", log)
    report = ctx.read("/var/lib/reports/latest.txt") or ""
    if "/srv/projects/alpha" not in report or "/srv/projects/beta" not in report:
        return ctx.failed(
            "The report the timer wrote does not list every project.", f"{report!r}\n{log}"
        )
    return ctx.passed("The timer's run succeeded and the report is complete.", report + log)
