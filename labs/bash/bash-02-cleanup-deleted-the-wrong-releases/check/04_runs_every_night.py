import os


def check(ctx):
    show = ctx.run(
        ["systemctl", "show", "prune-releases.service", "-p", "ExecStart", "-p", "LoadState"]
    ).out
    timer = ctx.run(["systemctl", "status", "prune-releases.timer", "--no-pager"]).text
    evidence = f"{show}\n{timer}"
    if not ctx.service_enabled("prune-releases.timer"):
        return ctx.failed("The timer is not enabled, so nothing schedules the cleanup.", evidence)
    if not ctx.service_active("prune-releases.timer"):
        return ctx.failed("The timer is not active.", evidence)
    program = ""
    for line in show.splitlines():
        if line.startswith("ExecStart=") and "path=" in line:
            program = line.split("path=", 1)[1].split(" ;", 1)[0].strip()
    if not program or not os.access(program, os.X_OK):
        return ctx.failed(
            f"The service would run {program or 'nothing'}, which is not an executable.", evidence
        )
    return ctx.passed(f"The timer is active and runs {program}.", evidence)
