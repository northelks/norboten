"""The tickets MCP server and its queue, a token for the job, and a repository whose .mcp.json
runs `python` (not installed) with the token under a misspelled variable — plus a committed local
settings file that disables the server and holds the token, and a job allowing a misspelled tool."""

import json
import os
import secrets
import shutil
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

USER = "learner"
HOME = "/home/learner"
REPO = f"{HOME}/support-digest"


def lab_file(ctx, name):
    with open(os.path.join(ctx.lab_dir, "files", name)) as f:
        return f.read()


def git(ctx, *args):
    ctx.run(["git", "-C", REPO, *args], user=USER, check=True)


def apply(ctx):
    token = ctx.state.get("token") or f"tk_live_{secrets.token_hex(12)}"
    ticket = ctx.state.get("ticket") or f"TCK-{secrets.randbelow(9000) + 1000}"
    ctx.state.update(token=token, ticket=ticket)
    ctx.save_state()

    ctx.write("/opt/tickets/tickets_mcp.py", lab_file(ctx, "tickets_mcp.py"), mode=0o755)
    ctx.write("/etc/tickets/token", token + "\n", mode=0o644)
    queue = [
        {"id": ticket, "status": "open", "priority": "high", "title": "Refund stuck in pending"},
        {"id": "TCK-0998", "status": "closed", "priority": "low", "title": "Typo on invoice"},
        {"id": "TCK-1001", "status": "open", "priority": "normal", "title": "Card declined twice"},
    ]
    ctx.write("/var/lib/tickets/queue.json", json.dumps(queue, indent=1) + "\n", mode=0o644)

    ctx.write(f"{HOME}/.config/support-digest/env", f"TICKETS_TOKEN={token}\n", mode=0o600)
    ctx.write(f"{HOME}/bin/support-digest", lab_file(ctx, "support-digest"), mode=0o755)

    shutil.rmtree(REPO, ignore_errors=True)
    ctx.write(f"{REPO}/README.md", "# support-digest\n\nThe morning digest of the support queue.\n")
    mcp = {
        "mcpServers": {
            "tickets": {
                "type": "stdio",
                "command": "python",
                "args": ["/opt/tickets/tickets_mcp.py"],
                "env": {"TICKETS_TOKEN": "${TICKET_TOKEN}"},
            }
        }
    }
    ctx.write(f"{REPO}/.mcp.json", json.dumps(mcp, indent=2) + "\n")
    local = {"disabledMcpjsonServers": ["tickets"], "env": {"TICKETS_TOKEN": token}}
    ctx.write(f"{REPO}/.claude/settings.local.json", json.dumps(local, indent=2) + "\n")
    ctx.run(["chown", "-R", f"{USER}:{USER}", REPO, f"{HOME}/.config", f"{HOME}/bin"], check=True)
    git(ctx, "init", "-q")
    git(ctx, "add", "-A")
    git(ctx, "commit", "-qm", "Digest reads the queue through the tickets MCP server")

    ctx.write("/etc/norboten/model.json", lab_file(ctx, "model.json"), mode=0o644)
    steps = json.loads(lab_file(ctx, "model.json"))
    claude_lab.run(steps, cwd=REPO, command=[f"{HOME}/bin/support-digest"], timeout=120)
