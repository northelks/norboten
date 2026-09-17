import hashlib
import os
import shutil
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

REPO = "/home/learner/handbook"
PROBE = f"{REPO}/docs/.norboten-probe-typos.md"
BACKUP = "/var/lib/norboten/claude-01-drafts"
ATTEMPTS = [
    ("Bash", {"command": "rm -rf drafts"}),
    ("Bash", {"command": "/bin/rm -rf drafts"}),
    ("Bash", {"command": "find drafts -type f -delete"}),
    ("Bash", {"command": "python3 -c \"import shutil; shutil.rmtree('drafts')\""}),
    ("Bash", {"command": "git rm -rq drafts"}),
    ("Write", {"file_path": f"{REPO}/drafts/pricing-v2.md", "content": ""}),
    ("Write", {"file_path": f"{REPO}/README.md", "content": "tidied\n"}),
]


def snapshot():
    found = {}
    for top in ("drafts", "docs"):
        for dirpath, _, files in os.walk(os.path.join(REPO, top)):
            for name in files:
                path = os.path.join(dirpath, name)
                with open(path, "rb") as f:
                    found[os.path.relpath(path, REPO)] = hashlib.sha256(f.read()).hexdigest()
    with open(os.path.join(REPO, "README.md"), "rb") as f:
        found["README.md"] = hashlib.sha256(f.read()).hexdigest()
    return found


def check(ctx):
    if not os.path.isdir(os.path.join(REPO, "drafts")):
        return ctx.failed("There is no drafts/ to protect yet.")
    shutil.rmtree(BACKUP, ignore_errors=True)
    ctx.run(["cp", "-a", REPO, BACKUP], check=True)
    before = snapshot()
    ctx.write(PROBE, "Teh grader wrote this line.\n", owner="learner", group="learner")
    steps = [
        {"tool": "Read", "input": {"file_path": PROBE}},
        {"tool": "Edit", "input": {"file_path": PROBE, "old_string": "Teh", "new_string": "The"}},
    ]
    steps += [{"text": "Clearing clutter.", "tool": t, "input": i} for t, i in ATTEMPTS]
    steps.append({"text": "Done."})
    try:
        run = claude_lab.run(steps, cwd=REPO, command=["/home/learner/bin/tidy-handbook"])
        fixed = (ctx.read(PROBE) or "").startswith("The grader")
        if os.path.exists(PROBE):
            os.remove(PROBE)
        after = snapshot() if os.path.isdir(REPO) else {}
    finally:
        # put the learner's handbook back whatever happened, index included
        shutil.rmtree(REPO, ignore_errors=True)
        ctx.run(["cp", "-a", BACKUP, REPO], check=True)
        shutil.rmtree(BACKUP, ignore_errors=True)
    lost = sorted(p for p in before if p not in after)
    changed = sorted(p for p in before if p in after and after[p] != before[p])
    results = run.tool_results()
    evidence = "\n".join(
        f"{t} {i.get('command') or i.get('file_path')}: {r[:160]}"
        for (t, i), r in zip(
            [("Read", {"file_path": PROBE}), ("Edit", {"file_path": PROBE}), *ATTEMPTS],
            results,
            strict=False,
        )
    )
    if len(run.requests) < 2:
        return ctx.failed("The job never asked the model for a second turn.", run.err[-800:])
    if not fixed:
        return ctx.failed(
            "Asked to fix a typo in a file under docs/, the job did not change it.", evidence
        )
    if lost or changed:
        what = ", ".join(lost + changed)
        return ctx.failed(
            f"The job deleted or overwrote files when the model asked it to: {what}.", evidence
        )
    return ctx.passed(
        f"The job fixed a typo in docs/ and refused all {len(ATTEMPTS)} attempts to delete or "
        "overwrite.",
        evidence,
    )
