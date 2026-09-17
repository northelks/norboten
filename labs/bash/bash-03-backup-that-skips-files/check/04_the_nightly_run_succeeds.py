import datetime
import os
import time


def _props(ctx):
    out = ctx.run(
        [
            "systemctl", "show", "backup-docs.service", "-p", "Result", "-p", "ExecMainStatus",
            "-p", "ExecMainExitTimestampMonotonic",
        ]
    ).out  # fmt: skip
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def check(ctx):
    if not (ctx.service_enabled("backup-docs.timer") and ctx.service_active("backup-docs.timer")):
        return ctx.failed("backup-docs.timer is not enabled and active.")
    props = _props(ctx)
    deadline = time.monotonic() + 25  # just after a boot, the timer's first run may still be due
    while props.get("ExecMainExitTimestampMonotonic", "0") == "0" and time.monotonic() < deadline:
        time.sleep(2)
        props = _props(ctx)
    log = ctx.run(["journalctl", "-u", "backup-docs.service", "-b", "-n", "12", "--no-pager"]).text
    if props.get("ExecMainExitTimestampMonotonic", "0") == "0":
        return ctx.failed("The timer has not run the backup since this boot.", log)
    if props.get("Result") != "success" or props.get("ExecMainStatus") != "0":
        return ctx.failed("The last run started by the timer failed.", log)
    today = os.path.join("/var/backups/docs", datetime.date.today().isoformat())
    missing = []
    for root, _, files in os.walk("/srv/docs"):
        for name in files:
            rel = os.path.relpath(os.path.join(root, name), "/srv/docs")
            if ctx.read(os.path.join(today, rel)) != ctx.read(os.path.join(root, name)):
                missing.append(rel)
    if missing:
        return ctx.failed(
            f"Today's backup is missing {len(missing)} of the documents.", f"{missing}\n{log}"
        )
    return ctx.passed("The timer's run succeeded and today's backup holds every document.", log)
