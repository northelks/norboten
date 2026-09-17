def check(ctx):
    target = ctx.run(["systemctl", "get-default"]).out.strip()
    if target != "multi-user.target":
        return ctx.failed(f"The system boots to {target}.", target)
    return ctx.passed("The system boots to multi-user.target.")
