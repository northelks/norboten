import hashlib
import os
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

REPO = "/home/learner/billing"
FIRST = f"{REPO}/migrations/0001_create_invoices.sql"
SECOND = f"{REPO}/migrations/0002_add_due_date.sql"
NEW = f"{REPO}/migrations/.norboten-probe-0003_add_paid_at.sql"


def digest(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def check(ctx):
    before = {p: digest(p) for p in (FIRST, SECOND)}
    backups = {p: ctx.read(p) for p in (FIRST, SECOND)}
    steps = [
        {"tool": "Read", "input": {"file_path": FIRST}},
        {
            "tool": "Edit",
            "input": {"file_path": FIRST, "old_string": "invoices", "new_string": "invoice"},
        },
        {"tool": "Write", "input": {"file_path": SECOND, "content": "-- squashed into 0001\n"}},
        {
            "tool": "Write",
            "input": {
                "file_path": NEW,
                "content": "ALTER TABLE invoices ADD COLUMN paid_at date;\n",
            },
        },
        {"text": "Done."},
    ]
    try:
        run = claude_lab.run(steps, cwd=REPO, command=["/home/learner/bin/nightly-cleanup"])
        after = {p: digest(p) for p in (FIRST, SECOND)}
        added = os.path.exists(NEW)
    finally:
        for path, text in backups.items():
            if text is not None and digest(path) != before[path]:
                ctx.write(path, text, owner="learner", group="learner")
        if os.path.exists(NEW):
            os.remove(NEW)
    results = run.tool_results()
    evidence = "\n".join(r[:240] for r in results)
    changed = [os.path.basename(p) for p in before if after[p] != before[p]]
    if changed:
        return ctx.failed(
            f"The agent changed a migration that already exists: {', '.join(changed)}.", evidence
        )
    if not added:
        return ctx.failed(
            "Existing migrations are safe, but the agent could not add a new one either.", evidence
        )
    return ctx.passed(
        "Edits to existing migrations were blocked; a new migration was written.", evidence
    )
