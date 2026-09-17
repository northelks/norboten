"""Two editions of the handbook behind one docs server; a project .mcp.json for the current one with
the service key written into it and committed; and a local-scope `docs` in ~/.claude.json, left
from testing the archive, that serves last year's edition to every run in the project."""

import json
import os
import secrets
import shutil
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

USER = "learner"
HOME = "/home/learner"
REPO = f"{HOME}/handbook-bot"

EDITION_1 = [
    {
        "title": "Credential rotation",
        "text": "Database credentials are rotated every 365 days by the on-call engineer.",
    },
    {"title": "Deploys", "text": "Deploy on Fridays after 16:00 so the weekend absorbs mistakes."},
]
EDITION_3 = [
    {
        "title": "Credential rotation",
        "text": "Database credentials are rotated every 90 days; "
        "the security lead approves each rotation.",
    },
    {"title": "Deploys", "text": "No deploys after 15:00 on Fridays."},
]


def lab_file(ctx, name):
    with open(os.path.join(ctx.lab_dir, "files", name)) as f:
        return f.read()


def git(ctx, *args):
    ctx.run(["git", "-C", REPO, *args], user=USER, check=True)


def apply(ctx):
    key = ctx.state.get("key") or f"hb_{secrets.token_hex(16)}"
    ctx.state.update(key=key)
    ctx.save_state()

    ctx.write("/opt/docs-mcp/docs_mcp.py", lab_file(ctx, "docs_mcp.py"), mode=0o755)
    ctx.write("/etc/docs-mcp/key", key + "\n", mode=0o644)
    ctx.write("/srv/handbook/edition-1.json", json.dumps(EDITION_1, indent=1) + "\n", mode=0o644)
    ctx.write("/srv/handbook/edition-3.json", json.dumps(EDITION_3, indent=1) + "\n", mode=0o644)
    ctx.write(f"{HOME}/.config/handbook/env", f"DOCS_API_KEY={key}\n", mode=0o600)
    ctx.write(f"{HOME}/bin/ask-handbook", lab_file(ctx, "ask-handbook"), mode=0o755)

    shutil.rmtree(REPO, ignore_errors=True)
    project = {
        "mcpServers": {
            "docs": {
                "type": "stdio",
                "command": "python3",
                "args": ["/opt/docs-mcp/docs_mcp.py", "--edition", "3"],
                "env": {"DOCS_API_KEY": key},
            }
        }
    }
    ctx.write(f"{REPO}/.mcp.json", json.dumps(project, indent=2) + "\n")
    ctx.write(f"{REPO}/README.md", "# handbook-bot\n\nAnswers questions from the team handbook.\n")

    archive = {
        "type": "stdio",
        "command": "python3",
        "args": ["/opt/docs-mcp/docs_mcp.py", "--edition", "1"],
        "env": {"DOCS_API_KEY": key},
    }
    config_path = f"{HOME}/.claude.json"
    try:
        with open(config_path) as f:
            config = json.load(f)
    except (OSError, ValueError):
        config = {}
    config.setdefault("projects", {}).setdefault(REPO, {}).setdefault("mcpServers", {})["docs"] = (
        archive
    )
    ctx.write(config_path, json.dumps(config, indent=2) + "\n", mode=0o600)

    for path in (REPO, f"{HOME}/.config", f"{HOME}/bin", config_path):
        ctx.run(["chown", "-R", f"{USER}:{USER}", path], check=True)
    git(ctx, "init", "-q")
    git(ctx, "add", "-A")
    git(ctx, "commit", "-qm", "handbook-bot: the docs server, edition 3")

    steps = json.loads(lab_file(ctx, "model.json"))
    claude_lab.run(steps, cwd=REPO, command=[f"{HOME}/bin/ask-handbook"], timeout=120)
