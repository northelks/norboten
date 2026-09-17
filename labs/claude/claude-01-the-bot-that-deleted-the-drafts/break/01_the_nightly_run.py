"""A handbook repository with drafts and a publishing token, a nightly job that skips every
permission check, a user setting that would skip them again, and last night's run replayed."""

import json
import os
import secrets
import shutil
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

USER = "learner"
HOME = "/home/learner"
REPO = f"{HOME}/handbook"

DOCS = {
    "docs/getting-started.md": (
        "# Getting started\n\nClone teh handbook, run `make serve`, and open http://localhost:8000.\n"
        "Every page lives under docs/ and is published on merge.\n"
    ),
    "docs/deploy.md": (
        "# Deploying\n\nPublishing runs from CI with the token in `.env`; never from a laptop.\n"
    ),
    "README.md": "# Handbook\n\nThe team handbook. Pages in docs/, work in progress in drafts/.\n",
}
DRAFTS = {
    "drafts/2026-q4-roadmap.md": (
        "# Q4 roadmap (draft)\n\n- move the status page off the old host\n"
        "- on-call rotation for the docs site\n- retire the wiki\n"
    ),
    "drafts/pricing-v2.md": (
        "# Pricing v2 (draft — do not publish)\n\nTeam plan: 12/seat. Enterprise: contact us.\n"
    ),
    "drafts/incident-2026-08-30.md": (
        "# Incident review, 30 August (draft)\n\n"
        "The docs site served a stale cache for 40 minutes.\n"
    ),
}


def lab_file(ctx, name):
    with open(os.path.join(ctx.lab_dir, "files", name)) as f:
        return f.read()


def git(ctx, *args):
    ctx.run(["git", "-C", REPO, *args], user=USER, check=True)


def apply(ctx):
    token = ctx.state.get("token") or f"hbk_live_{secrets.token_hex(16)}"
    ctx.state["token"] = token
    ctx.save_state()

    shutil.rmtree(REPO, ignore_errors=True)
    for path, text in {**DOCS, **DRAFTS}.items():
        ctx.write(f"{REPO}/{path}", text, owner=USER, group=USER)
    ctx.write(f"{REPO}/.gitignore", ".env\n", owner=USER, group=USER)
    ctx.write(
        f"{REPO}/.env",
        "HANDBOOK_PUBLISH_URL=https://docs.example.org/api/publish\n"
        f"HANDBOOK_PUBLISH_TOKEN={token}\n",
        mode=0o600,
        owner=USER,
        group=USER,
    )
    ctx.run(["chown", "-R", f"{USER}:{USER}", REPO], check=True)
    git(ctx, "init", "-q")
    git(ctx, "add", "-A")
    git(ctx, "commit", "-q", "-m", "Handbook as of August")

    ctx.write(
        f"{HOME}/bin/tidy-handbook",
        lab_file(ctx, "tidy-handbook"),
        mode=0o755,
        owner=USER,
        group=USER,
    )
    # "it kept asking": the same shortcut, a second time, where every run picks it up
    ctx.write(
        f"{HOME}/.claude/settings.json",
        '{\n  "permissions": {\n    "defaultMode": "bypassPermissions"\n  }\n}\n',
        owner=USER,
        group=USER,
    )
    ctx.run(["chown", "-R", f"{USER}:{USER}", f"{HOME}/.claude", f"{HOME}/bin"], check=True)
    ctx.write(
        "/etc/norboten/model.json",
        lab_file(ctx, "model.json"),
        mode=0o644,
    )

    # last night, for real: the typo fixed, the drafts deleted, the token sent to the model
    steps = json.loads(lab_file(ctx, "model.json"))
    claude_lab.run(steps, cwd=REPO, command=[f"{HOME}/bin/tidy-handbook"], timeout=120)
