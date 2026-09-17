"""The files MCP server for the team's notes, configured to share / for writing, with links
followed and dotfiles shown; a notes folder holding a link to ~/.ssh and a .env; and the job."""

import json
import os
import secrets
import shutil
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

USER = "learner"
HOME = "/home/learner"
NOTES = f"{HOME}/notes"
BOT = f"{HOME}/notes-bot"

RUNBOOK = """# On-call runbook

Page the secondary if the primary has not acknowledged within ten minutes. Never page between
02:00 and 06:00 for a warning; wait for the morning review. Escalation list: notes/oncall.md.
"""

ONCALL = """# On-call rota

| week | primary | secondary |
|---|---|---|
| 38 | dana | lee |
| 39 | lee | sam |
"""


def lab_file(ctx, name):
    with open(os.path.join(ctx.lab_dir, "files", name)) as f:
        return f.read()


def apply(ctx):
    webhook = ctx.state.get("webhook") or f"https://hooks.example/T{secrets.token_hex(8)}"
    token = ctx.state.get("token") or f"nb_{secrets.token_hex(16)}"
    ctx.state.update(webhook=webhook, token=token)
    ctx.save_state()

    ctx.write("/opt/mcp-files/files_mcp.py", lab_file(ctx, "files_mcp.py"), mode=0o755)
    conf = {"roots": ["/"], "follow_symlinks": True, "show_hidden": True, "read_only": False}
    ctx.write("/etc/mcp-files/config.json", json.dumps(conf, indent=2) + "\n", mode=0o644)

    shutil.rmtree(NOTES, ignore_errors=True)
    ctx.write(f"{NOTES}/runbook.md", RUNBOOK)
    ctx.write(f"{NOTES}/oncall.md", ONCALL)
    ctx.write(f"{NOTES}/.env", f"ALERT_WEBHOOK={webhook}\n", mode=0o600)
    ctx.write(
        f"{HOME}/.ssh/id_ed25519", "-----BEGIN OPENSSH PRIVATE KEY-----\n(lab key)\n", mode=0o600
    )
    if not os.path.islink(f"{NOTES}/shared-keys"):
        os.symlink(f"{HOME}/.ssh", f"{NOTES}/shared-keys")
    ctx.write(f"{HOME}/.config/notes-bot/token", token + "\n", mode=0o600)

    mcp = {
        "mcpServers": {
            "files": {
                "type": "stdio",
                "command": "python3",
                "args": ["/opt/mcp-files/files_mcp.py"],
            }
        }
    }
    ctx.write(f"{BOT}/.mcp.json", json.dumps(mcp, indent=2) + "\n")
    ctx.write(f"{HOME}/bin/ask-notes", lab_file(ctx, "ask-notes"), mode=0o755)
    for path in (NOTES, BOT, f"{HOME}/.ssh", f"{HOME}/.config", f"{HOME}/bin"):
        ctx.run(["chown", "-R", f"{USER}:{USER}", path], check=True)
    os.chmod(f"{HOME}/.ssh", 0o700)

    steps = json.loads(lab_file(ctx, "model.json"))
    claude_lab.run(steps, cwd=BOT, command=[f"{HOME}/bin/ask-notes"], timeout=120)
