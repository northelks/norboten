def check(ctx):
    policy = ctx.run(["systemctl", "show", "-p", "Restart", "--value", "notes"]).out.strip()
    if policy in ("", "no"):
        return ctx.failed(
            "When notes crashes, nothing brings it back.", f"Restart={policy or 'no'}"
        )
    return ctx.passed(f"systemd restarts notes when it dies (Restart={policy}).")
