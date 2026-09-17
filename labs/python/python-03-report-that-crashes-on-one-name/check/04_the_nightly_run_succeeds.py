import time


def _props(ctx):
    out = ctx.run(
        [
            "systemctl", "show", "members-report.service", "-p", "Result", "-p", "ExecMainStatus",
            "-p", "ExecMainExitTimestampMonotonic",
        ]
    ).out  # fmt: skip
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def check(ctx):
    if not (
        ctx.service_enabled("members-report.timer") and ctx.service_active("members-report.timer")
    ):
        return ctx.failed("members-report.timer is not enabled and active.")
    props = _props(ctx)
    deadline = time.monotonic() + 25  # just after a boot, the timer's first run may still be due
    while props.get("ExecMainExitTimestampMonotonic", "0") == "0" and time.monotonic() < deadline:
        time.sleep(2)
        props = _props(ctx)
    log = ctx.run(
        ["journalctl", "-u", "members-report.service", "-b", "-n", "12", "--no-pager"]
    ).text
    if props.get("ExecMainExitTimestampMonotonic", "0") == "0":
        return ctx.failed("The timer has not run the report since this boot.", log)
    if props.get("Result") != "success" or props.get("ExecMainStatus") != "0":
        return ctx.failed("The last run started by the timer failed.", log)
    summary = ctx.read("/var/lib/members/summary.csv") or ""
    missing = [c for c in ("Kraków", "München", "Málaga", "Nîmes") if c not in summary]
    if missing:
        return ctx.failed(
            f"The summary is missing {len(missing)} of the cities.", f"{missing}\n{summary}\n{log}"
        )
    for name in ("Ruiz Peña", "Anaïs Fabre"):
        if name not in summary:
            return ctx.failed("The summary does not hold every member's name.", f"{summary}\n{log}")
    return ctx.passed("The timer's run succeeded and the summary is complete.", summary + log)
