"""Redis with persistence off and no volume, published on every interface, holding real jobs."""

import os
import shutil
import time

JOBS = 50


def apply(ctx):
    shutil.copy(os.path.join(ctx.lab_dir, "files", "jobs-redis.service"), "/etc/systemd/system/")
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "--now", "docker.service"], check=True, timeout=90)
    ctx.run(["systemctl", "enable", "--now", "jobs-redis.service"], check=True, timeout=60)
    for _ in range(30):
        if ctx.run(["docker", "exec", "jobs-redis", "redis-cli", "ping"]).out.strip() == "PONG":
            break
        time.sleep(1)
    else:
        raise RuntimeError("jobs-redis did not answer")
    if (
        ctx.run(["docker", "exec", "jobs-redis", "redis-cli", "llen", "jobs:pending"]).out.strip()
        == "0"
    ):
        jobs = [f"report:{n:03d}" for n in range(1, JOBS + 1)]
        ctx.run(
            ["docker", "exec", "jobs-redis", "redis-cli", "rpush", "jobs:pending", *jobs],
            check=True,
        )
    ctx.state["jobs"] = JOBS
