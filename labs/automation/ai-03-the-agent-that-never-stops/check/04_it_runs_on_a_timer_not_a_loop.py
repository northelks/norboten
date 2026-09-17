def show(ctx, unit, *props):
    out = ctx.run(["systemctl", "show", unit, *(f"--property={p}" for p in props)]).out
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def check(ctx):
    service = show(ctx, "inbox-agent.service", "Type", "Restart", "RuntimeMaxUSec", "UnitFileState")
    timer = show(ctx, "inbox-agent.timer", "ActiveState", "UnitFileState", "LoadState")
    evidence = f"service: {service}\ntimer: {timer}"
    if timer.get("LoadState") != "loaded":
        return ctx.failed("There is no inbox-agent.timer.", evidence)
    if timer.get("UnitFileState") != "enabled" or timer.get("ActiveState") != "active":
        return ctx.failed("inbox-agent.timer is not enabled and active.", evidence)
    if service.get("Restart") == "always":
        return ctx.failed("The service still restarts whenever it exits.", evidence)
    if service.get("Type") != "oneshot":
        return ctx.failed(
            f"The service is Type={service.get('Type')}, not a one-shot job.", evidence
        )
    if service.get("RuntimeMaxUSec") in (None, "", "infinity"):
        return ctx.failed("A run of the agent has no time limit.", evidence)
    if service.get("UnitFileState") == "enabled":
        return ctx.failed("The service is also enabled to start at boot on its own.", evidence)
    return ctx.passed("A timer starts the agent as a one-shot job with a time limit.", evidence)
