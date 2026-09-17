import json


def _containers(ctx, service):
    ids = ctx.run(
        [
            "docker",
            "ps",
            "--all",
            "--quiet",
            "--filter",
            "label=com.docker.compose.project=shop",
            "--filter",
            f"label=com.docker.compose.service={service}",
        ]
    ).out.split()
    if not ids:
        return []
    r = ctx.run(["docker", "inspect", *ids])
    try:
        return json.loads(r.out)
    except ValueError:
        return []


def check(ctx):
    api = _containers(ctx, "api")
    if not api:
        return ctx.failed("The shop project has no api container.")
    published = {
        c["Name"].lstrip("/"): {
            port: bindings
            for port, bindings in (c.get("HostConfig", {}).get("PortBindings") or {}).items()
            if bindings
        }
        for c in api
    }
    evidence = json.dumps(published, indent=2)
    if any(published.values()):
        return ctx.failed("The api service is published on a host port.", evidence)
    if not any(c.get("State", {}).get("Running") for c in api):
        return ctx.failed("The api container is not running.", evidence)
    return ctx.passed("api runs without any published port.", evidence)
