import json
import time


def _props(ctx):
    out = ctx.run(
        [
            "systemctl",
            "show",
            "sync.service",
            "-p",
            "Result",
            "-p",
            "ExecMainStatus",
            "-p",
            "ExecMainExitTimestampMonotonic",
        ]
    ).out
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def check(ctx):
    if not (ctx.service_enabled("sync.timer") and ctx.service_active("sync.timer")):
        return ctx.failed("sync.timer is not enabled and active.")
    props = _props(ctx)
    deadline = time.monotonic() + 20  # just after a boot, the timer's first run may still be due
    while props.get("ExecMainExitTimestampMonotonic", "0") == "0" and time.monotonic() < deadline:
        time.sleep(2)
        props = _props(ctx)
    log = ctx.run(["journalctl", "-u", "sync.service", "-b", "-n", "12", "--no-pager"]).text
    if props.get("ExecMainExitTimestampMonotonic", "0") == "0":
        return ctx.failed("The timer has not run the sync since this boot.", log)
    if props.get("Result") != "success" or props.get("ExecMainStatus") != "0":
        return ctx.failed("The last run started by the timer failed.", log)
    try:
        records = json.loads(ctx.read("/var/lib/sync/records.json") or "")
    except ValueError:
        return ctx.failed("The records file is not valid JSON.", log)
    hosts = sorted(r.get("host", "") for r in records if isinstance(r, dict))
    if hosts != ["db01", "web01", "web02"]:
        return ctx.failed("The records file does not hold the API's records.", f"{hosts}\n{log}")
    return ctx.passed("The timer's run succeeded and the records are current.", log)
