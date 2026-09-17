def check(ctx):
    invocation = ctx.run(
        ["systemctl", "show", "deploy.service", "-p", "InvocationID", "--value"]
    ).out.strip()
    result = ctx.run(["systemctl", "show", "deploy.service", "-p", "Result", "--value"]).out
    if not invocation:
        return ctx.failed("deploy.service has not run since this boot.")
    if result.strip() != "success":
        return ctx.failed("The last deploy did not complete, so its log shows nothing yet.")
    log = ctx.run(
        ["journalctl", f"_SYSTEMD_INVOCATION_ID={invocation}", "--no-pager", "-o", "cat"]
    ).out
    if not log.strip():
        return ctx.failed("The last run of deploy.service left no log to inspect.")
    if ctx.state["db_password"] in log:
        lines = [line for line in log.splitlines() if ctx.state["db_password"] in line]
        redacted = "\n".join(line.replace(ctx.state["db_password"], "<password>") for line in lines)
        return ctx.failed("The last deploy wrote the database password to its log.", redacted)
    return ctx.passed("The last deploy's log does not contain the password.", log[-1500:])
