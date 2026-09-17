import os
import pwd
import time


def _props(ctx):
    out = ctx.run(
        [
            "systemctl",
            "show",
            "deploy.service",
            "-p",
            "ActiveState",
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
    if not ctx.service_enabled("deploy.service"):
        return ctx.failed("deploy.service does not run at boot.")
    props = _props(ctx)
    deadline = time.monotonic() + 25  # at boot the playbook may still be running
    while props.get("ActiveState") == "activating" and time.monotonic() < deadline:
        time.sleep(2)
        props = _props(ctx)
    log = ctx.run(["journalctl", "-u", "deploy.service", "-b", "-n", "15", "--no-pager"]).text
    if props.get("ExecMainExitTimestampMonotonic", "0") == "0":
        return ctx.failed("deploy.service has not finished a run since this boot.", log)
    if props.get("Result") != "success" or props.get("ExecMainStatus") != "0":
        return ctx.failed("The last run of deploy.service failed.", log)
    path = "/srv/app/config/db.conf"
    text = ctx.read(path)
    if text is None:
        return ctx.failed("The deploy succeeded but wrote no database settings.", log)
    if f"password = {ctx.state['db_password']}" not in text:
        return ctx.failed("The database settings do not hold the password from the vault.", log)
    st = os.stat(path)
    owner = pwd.getpwuid(st.st_uid).pw_name
    return ctx.passed("deploy.service rendered the settings at boot.", f"{path} owner {owner}")
