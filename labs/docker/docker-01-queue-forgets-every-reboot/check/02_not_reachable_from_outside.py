import json


def check(ctx):
    inspect = ctx.run(["docker", "inspect", "jobs-redis"])
    try:
        info = json.loads(inspect.out)[0]
    except (ValueError, IndexError):
        return ctx.failed("jobs-redis is not running.", inspect.text)
    bindings = info.get("HostConfig", {}).get("PortBindings") or {}
    mode = info.get("HostConfig", {}).get("NetworkMode")
    listening = ctx.run(["ss", "-Hltn", "sport = :6379"]).out
    evidence = f"network mode: {mode}\nport bindings: {bindings}\nlistening:\n{listening}"
    if mode == "host":
        return ctx.failed(
            "The container shares the host's network, so Redis listens everywhere.", evidence
        )
    exposed = [
        b
        for ports in bindings.values()
        for b in (ports or [])
        if b.get("HostIp", "") not in ("127.0.0.1", "::1")
    ]
    if exposed:
        return ctx.failed("A port of the container is published on every interface.", evidence)
    wide = [
        line for line in listening.splitlines() if not ("127.0.0.1:" in line or "[::1]:" in line)
    ]
    if wide:
        return ctx.failed("Something listens on port 6379 beyond the loopback.", evidence)
    if not any("127.0.0.1:6379" in line or "[::1]:6379" in line for line in listening.splitlines()):
        return ctx.failed("Redis is not published on 127.0.0.1:6379 for the workers.", evidence)
    return ctx.passed("Redis is reachable only through the loopback.", evidence)
