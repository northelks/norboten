import json
import time


def check(ctx):
    count = ctx.state.get("jobs", 50)
    want = [f"report:{n:03d}" for n in range(1, count + 1)]
    if not ctx.service_enabled("docker.service") or not ctx.service_enabled("jobs-redis.service"):
        return ctx.failed("Docker or jobs-redis.service does not start at boot.")
    for _ in range(15):  # after a boot, the container may still be starting
        if ctx.run(["docker", "exec", "jobs-redis", "redis-cli", "ping"]).out.strip() == "PONG":
            break
        time.sleep(2)
    r = ctx.run(["docker", "exec", "jobs-redis", "redis-cli", "lrange", "jobs:pending", "0", "-1"])
    got = r.out.split()
    evidence = f"{len(got)} jobs: {' '.join(got[:5])}{' …' if len(got) > 5 else ''}\n{r.err}"
    if got != want:
        return ctx.failed(
            f"jobs:pending holds {len(got)} of the {count} jobs, or not in order.", evidence
        )
    inspect = ctx.run(["docker", "inspect", "jobs-redis"])
    try:
        info = json.loads(inspect.out)[0]
    except (ValueError, IndexError):
        return ctx.failed("jobs-redis cannot be inspected.", inspect.text)
    mounts = [m for m in info.get("Mounts", []) if m.get("Destination") == "/data"]
    save = ctx.run(
        ["docker", "exec", "jobs-redis", "redis-cli", "config", "get", "save"]
    ).out.split("\n")
    aof = ctx.run(
        ["docker", "exec", "jobs-redis", "redis-cli", "config", "get", "appendonly"]
    ).out.split()
    persistent = (len(save) > 1 and save[1].strip()) or aof[-1:] == ["yes"]
    evidence += f"\n/data mounts: {mounts}\nsave: {save[1:2]}\nappendonly: {aof[-1:]}"
    if not mounts:
        return ctx.failed(
            "Redis keeps its data inside the container, which dies with it.", evidence
        )
    if not persistent:
        return ctx.failed("Redis is configured never to write its data to disk.", evidence)
    return ctx.passed(f"All {count} jobs are there, on persistent storage.", evidence)
