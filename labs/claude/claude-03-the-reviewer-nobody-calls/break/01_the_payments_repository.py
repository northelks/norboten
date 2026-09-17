"""A payments repository with a branch to review, the review job, and the security-reviewer
subagent written in the wrong directory, with `desc:` for `description:`, no tool list and Opus."""

import json
import os
import shutil
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

USER = "learner"
HOME = "/home/learner"
REPO = f"{HOME}/payments"

MAIN = {
    "README.md": "# payments\n\nRefunds and card payments. Every branch gets a security review.\n",
    "payments/refunds.py": (
        "def find_refunds(db, customer_id):\n"
        '    return db.execute("SELECT * FROM refunds WHERE customer_id = %s", (customer_id,))\n'
    ),
}
BRANCH = {
    "payments/refunds.py": (
        "def find_refunds(db, customer_id, text=''):\n"
        '    sql = "SELECT * FROM refunds WHERE customer_id = %s" % customer_id\n'
        "    if text:\n"
        '        sql += " AND note LIKE \'%" + text + "%\'"\n'
        "    return db.execute(sql)\n"
    ),
}


def lab_file(ctx, name):
    with open(os.path.join(ctx.lab_dir, "files", name)) as f:
        return f.read()


def git(ctx, *args):
    ctx.run(["git", "-C", REPO, *args], user=USER, check=True)


def apply(ctx):
    shutil.rmtree(REPO, ignore_errors=True)
    for path, text in MAIN.items():
        ctx.write(f"{REPO}/{path}", text)
    ctx.write(f"{REPO}/.claude/agent/security-reviewer.md", lab_file(ctx, "security-reviewer.md"))
    ctx.run(["chown", "-R", f"{USER}:{USER}", REPO], check=True)
    git(ctx, "init", "-q")
    git(ctx, "add", "-A")
    git(ctx, "commit", "-qm", "Refund lookup")
    git(ctx, "switch", "-qc", "feature/refund-search")
    for path, text in BRANCH.items():
        ctx.write(f"{REPO}/{path}", text, owner=USER, group=USER)
    git(ctx, "commit", "-qam", "Search refunds by note")

    ctx.write(f"{HOME}/bin/review-diff", lab_file(ctx, "review-diff"), mode=0o755)
    ctx.run(["chown", "-R", f"{USER}:{USER}", f"{HOME}/bin"], check=True)
    ctx.write("/etc/norboten/model.json", lab_file(ctx, "model.json"), mode=0o644)

    steps = json.loads(lab_file(ctx, "model.json"))
    claude_lab.run(steps, cwd=REPO, command=[f"{HOME}/bin/review-diff"], timeout=120)
