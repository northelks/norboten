"""A billing repository with a bare origin, three guard-rail hooks that each fail differently —
a lower-case matcher and an argument that never arrives, exit 1 instead of 2, a script that is not
executable — and last night's run replayed through them."""

import hashlib
import json
import os
import shutil
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

USER = "learner"
HOME = "/home/learner"
REPO = f"{HOME}/billing"
ORIGIN = "/srv/git/billing.git"
APPLIED = "migrations/0002_add_due_date.sql"

SOURCES = {
    "README.md": "# billing\n\nInvoices and payments. Migrations in migrations/ run on deploy.\n",
    "app/__init__.py": "",
    "app/invoices.py": (
        "from dataclasses import dataclass\nfrom datetime import date\n\n\n@dataclass\n"
        "class Invoice:\n    number: str\n    amount_cents: int\n    due: date\n"
        "    paid: bool = False\n\n\ndef open_invoices():\n    # TODO: an overdue report\n"
        "    return []\n"
    ),
    "migrations/0001_create_invoices.sql": (
        "CREATE TABLE invoices (\n    number text PRIMARY KEY,\n"
        "    amount_cents integer NOT NULL\n);\n"
    ),
    APPLIED: (
        "ALTER TABLE invoices\n    ADD COLUMN due date NOT NULL DEFAULT CURRENT_DATE;"
        "  -- when payment is due\n"
    ),
}


def lab_file(ctx, *name):
    with open(os.path.join(ctx.lab_dir, "files", *name)) as f:
        return f.read()


def as_learner(ctx, *cmd):
    ctx.run(list(cmd), user=USER, check=True)


def apply(ctx):
    ctx.state["applied_sha256"] = hashlib.sha256(SOURCES[APPLIED].encode()).hexdigest()
    ctx.save_state()

    shutil.rmtree(REPO, ignore_errors=True)
    shutil.rmtree(ORIGIN, ignore_errors=True)
    os.makedirs("/srv/git", exist_ok=True)
    ctx.run(["chown", f"{USER}:{USER}", "/srv/git"], check=True)
    as_learner(ctx, "git", "init", "-q", "--bare", ORIGIN)
    for path, text in SOURCES.items():
        ctx.write(f"{REPO}/{path}", text)
    ctx.write(f"{REPO}/.claude/settings.json", lab_file(ctx, "settings.json"))
    for hook, mode in (("tidy.sh", 0o755), ("no-push.sh", 0o755), ("protect-migrations.sh", 0o644)):
        ctx.write(f"{REPO}/.claude/hooks/{hook}", lab_file(ctx, "hooks", hook), mode=mode)
    ctx.run(["chown", "-R", f"{USER}:{USER}", REPO], check=True)
    as_learner(ctx, "git", "-C", REPO, "init", "-q")
    as_learner(ctx, "git", "-C", REPO, "add", "-A")
    as_learner(ctx, "git", "-C", REPO, "commit", "-qm", "Invoices with due dates (0002 applied)")
    as_learner(ctx, "git", "-C", REPO, "remote", "add", "origin", ORIGIN)
    as_learner(ctx, "git", "-C", REPO, "push", "-q", "origin", "main")

    ctx.write(f"{HOME}/bin/nightly-cleanup", lab_file(ctx, "nightly-cleanup"), mode=0o755)
    ctx.run(["chown", "-R", f"{USER}:{USER}", f"{HOME}/bin"], check=True)
    ctx.write("/etc/norboten/model.json", lab_file(ctx, "model.json"), mode=0o644)

    # last night: the file written untidied, the migration edited, committed and pushed
    steps = json.loads(lab_file(ctx, "model.json"))
    claude_lab.run(steps, cwd=REPO, command=[f"{HOME}/bin/nightly-cleanup"], timeout=120)
