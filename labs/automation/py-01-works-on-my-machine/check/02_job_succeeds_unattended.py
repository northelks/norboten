import datetime
import json
import os

REPORT = "/var/lib/etl/reports/latest.json"


def _boot_time():
    with open("/proc/stat") as f:
        for line in f:
            if line.startswith("btime "):
                return int(line.split()[1])
    return 0


def check(ctx):
    show = ctx.run(
        [
            "systemctl",
            "show",
            "etl-report.service",
            "-p",
            "Result",
            "-p",
            "ExecMainExitTimestampMonotonic",
            "-p",
            "ExecMainStatus",
        ]
    ).out
    props = dict(line.split("=", 1) for line in show.splitlines() if "=" in line)
    log = ctx.run(["journalctl", "-u", "etl-report.service", "-b", "-n", "15", "--no-pager"]).text
    if props.get("ExecMainExitTimestampMonotonic", "0") == "0":
        return ctx.failed("systemd has not run the job since this boot.", log)
    if props.get("Result") != "success" or props.get("ExecMainStatus") != "0":
        return ctx.failed("The last run by systemd failed.", log)
    try:
        st = os.stat(REPORT)
        report = json.loads(ctx.read(REPORT) or "")
    except (OSError, ValueError) as e:
        return ctx.failed("The job ran but there is no valid report.", str(e))
    if st.st_mtime < _boot_time():
        return ctx.failed("The report is older than this boot.", str(report))
    if report.get("count") != 3:
        return ctx.failed("The report does not contain the API's metrics.", str(report))
    stamp = datetime.datetime.fromtimestamp(st.st_mtime, datetime.UTC).isoformat()
    return ctx.passed("systemd ran the job and it wrote a fresh report.", f"{stamp} {report}")
