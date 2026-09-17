import os


def check(ctx):
    masked = []
    for unit in ("inventory-api.service", "config-sync.service"):
        state = ctx.run(["systemctl", "is-enabled", unit]).out.strip()
        link = f"/etc/systemd/system/{unit}"
        if state.startswith("masked") or (
            os.path.islink(link) and os.readlink(link) == "/dev/null"
        ):
            masked.append(f"{unit}: {state}")
    if masked:
        return ctx.failed("A unit this lab needs is masked.", "\n".join(masked))
    return ctx.passed("No lab unit is masked.")
