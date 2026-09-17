"""The reports MCP server listening on every address, behind an nginx that buffers its event
stream and gives up after two silent seconds, and the weekly job that asks for a report."""

import json
import os
import secrets
import shutil
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

USER = "learner"
HOME = "/home/learner"
REPO = f"{HOME}/ops-report"


def lab_file(ctx, name):
    with open(os.path.join(ctx.lab_dir, "files", name)) as f:
        return f.read()


def apply(ctx):
    report = ctx.state.get("report") or f"W{secrets.randbelow(40) + 10}-{secrets.token_hex(2)}"
    ctx.state.update(report=report)
    ctx.save_state()

    ctx.write("/var/lib/reports/id", report + "\n", mode=0o644)
    ctx.write("/opt/reports-mcp/reports_mcp.py", lab_file(ctx, "reports_mcp.py"), mode=0o755)
    ctx.write("/usr/local/bin/reports-mcp", lab_file(ctx, "reports-mcp"), mode=0o755)
    ctx.write("/usr/local/bin/proxy-restart", lab_file(ctx, "proxy-restart"), mode=0o755)
    conf = {"bind": "0.0.0.0", "port": 8931, "step_seconds": 3}
    ctx.write("/etc/reports-mcp/config.json", json.dumps(conf, indent=2) + "\n", mode=0o644)
    ctx.write("/etc/nginx/conf.d/reports.conf", lab_file(ctx, "reports.conf"), mode=0o644)
    ctx.run(["/usr/local/bin/reports-mcp", "restart"], check=True)
    ctx.run(["/usr/local/bin/proxy-restart"], check=True)

    shutil.rmtree(REPO, ignore_errors=True)
    mcp = {"mcpServers": {"reports": {"type": "http", "url": "http://127.0.0.1:8080/mcp"}}}
    ctx.write(f"{REPO}/.mcp.json", json.dumps(mcp, indent=2) + "\n")
    ctx.write(f"{HOME}/bin/weekly-report", lab_file(ctx, "weekly-report"), mode=0o755)
    for path in (REPO, f"{HOME}/bin"):
        ctx.run(["chown", "-R", f"{USER}:{USER}", path], check=True)

    steps = json.loads(lab_file(ctx, "model.json"))
    claude_lab.run(steps, cwd=REPO, command=[f"{HOME}/bin/weekly-report"], timeout=120)
