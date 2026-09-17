import json
import time

ALWAYS = ("always", "unless-stopped")


def _state(ctx):
    ids = ctx.run(
        ["docker", "ps", "--all", "--quiet", "--filter", "label=com.docker.compose.project=shop"]
    ).out.split()
    if not ids:
        return {}
    try:
        info = json.loads(ctx.run(["docker", "inspect", *ids]).out)
    except ValueError:
        return {}
    return {
        c["Config"]["Labels"].get("com.docker.compose.service", c["Name"]): (
            c["State"].get("Running", False),
            c["HostConfig"].get("RestartPolicy", {}).get("Name", ""),
        )
        for c in info
    }


def _unit_starts_stack(ctx):
    units = ctx.run(
        ["systemctl", "list-unit-files", "--state=enabled", "--type=service", "--no-legend"]
    ).out
    for line in units.splitlines():
        name = line.split()[0]
        cat = ctx.run(["systemctl", "cat", name]).out
        if "compose" in cat and "/srv/shop" in cat:
            return name
    return ""


def check(ctx):
    if not ctx.service_enabled("docker.service"):
        return ctx.failed("Docker does not start at boot.")
    state = _state(ctx)
    deadline = time.monotonic() + 20
    while not all(running for running, _ in state.values()) and time.monotonic() < deadline:
        time.sleep(2)
        state = _state(ctx)
    evidence = "\n".join(f"{s}: running={r} restart={p or 'no'}" for s, (r, p) in state.items())
    if set(state) != {"web", "api"}:
        return ctx.failed(
            "The shop project does not have exactly its web and api services.", evidence
        )
    stopped = [s for s, (running, _) in state.items() if not running]
    if stopped:
        return ctx.failed(f"Not running: {', '.join(sorted(stopped))}.", evidence)
    unit = _unit_starts_stack(ctx)
    if not unit and not all(policy in ALWAYS for _, policy in state.values()):
        return ctx.failed("Nothing would start these containers again after a reboot.", evidence)
    how = f"by {unit}" if unit else "by their restart policy"
    return ctx.passed(f"web and api are running, and are started at boot {how}.", evidence)
