def check(ctx):
    user = ctx.run(["systemctl", "show", "-p", "User", "--value", "etl-report.service"]).out
    user = user.strip()
    unit = ctx.run(["systemctl", "cat", "etl-report.service"]).text
    if user != "etl":
        return ctx.failed(f"The job runs as {user or 'root'}.", unit)
    return ctx.passed("The job runs as etl.", unit)
