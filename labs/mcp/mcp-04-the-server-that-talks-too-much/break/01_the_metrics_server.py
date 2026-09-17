"""The metrics MCP server with its debug log on stdout, started through a wrapper that prints a
banner there first, and the health-check job that asks it."""

import json
import os
import shutil
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

USER = "learner"
HOME = "/home/learner"
REPO = f"{HOME}/ops"


def lab_file(ctx, name):
    with open(os.path.join(ctx.lab_dir, "files", name)) as f:
        return f.read()


def apply(ctx):
    ctx.write("/opt/metrics-mcp/metrics_mcp.py", lab_file(ctx, "metrics_mcp.py"), mode=0o755)
    ctx.write("/usr/local/bin/metrics-mcp", lab_file(ctx, "metrics-mcp"), mode=0o755)
    conf = {"log_level": "debug", "log_to": "stdout"}
    ctx.write("/etc/metrics-mcp/config.json", json.dumps(conf, indent=2) + "\n", mode=0o644)
    ctx.write("/var/log/metrics-mcp.log", "", mode=0o666)

    shutil.rmtree(REPO, ignore_errors=True)
    mcp = {"mcpServers": {"metrics": {"type": "stdio", "command": "/usr/local/bin/metrics-mcp"}}}
    ctx.write(f"{REPO}/.mcp.json", json.dumps(mcp, indent=2) + "\n")
    ctx.write(f"{HOME}/bin/health-check", lab_file(ctx, "health-check"), mode=0o755)
    for path in (REPO, f"{HOME}/bin"):
        ctx.run(["chown", "-R", f"{USER}:{USER}", path], check=True)

    steps = json.loads(lab_file(ctx, "model.json"))
    claude_lab.run(steps, cwd=REPO, command=[f"{HOME}/bin/health-check"], timeout=120)
