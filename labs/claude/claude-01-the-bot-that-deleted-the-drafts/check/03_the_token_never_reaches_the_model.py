import os
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

REPO = "/home/learner/handbook"
PROBE = f"{REPO}/docs/.norboten-probe-typos.md"
ATTEMPTS = [
    ("Read", {"file_path": f"{REPO}/.env"}),
    ("Bash", {"command": "cat .env"}),
    ("Grep", {"pattern": "TOKEN", "path": REPO, "output_mode": "content", "glob": ".env*"}),
    ("Bash", {"command": "grep -r HANDBOOK_PUBLISH_TOKEN ."}),
    ("Bash", {"command": "env"}),
]


def check(ctx):
    token = ctx.state.get("token")
    if not token:
        return ctx.failed("The lab's token was never recorded; start the lab again.")
    ctx.write(PROBE, "Teh grader wrote this line.\n", owner="learner", group="learner")
    steps = [
        {"tool": "Read", "input": {"file_path": PROBE}},
        {"tool": "Edit", "input": {"file_path": PROBE, "old_string": "Teh", "new_string": "The"}},
    ]
    steps += [{"text": "Checking the publish config.", "tool": t, "input": i} for t, i in ATTEMPTS]
    steps.append({"text": "Done."})
    try:
        run = claude_lab.run(steps, cwd=REPO, command=["/home/learner/bin/tidy-handbook"])
        fixed = (ctx.read(PROBE) or "").startswith("The grader")
    finally:
        if os.path.exists(PROBE):
            os.remove(PROBE)
    results = run.tool_results()[2:]
    evidence = "\n".join(
        f"{t} {i.get('command') or i.get('file_path') or i.get('pattern')}: "
        f"{r[:160].replace(token, '<the token>')}"
        for (t, i), r in zip(ATTEMPTS, results, strict=False)
    )
    if len(run.requests) < 2:
        return ctx.failed("The job never asked the model for a second turn.", run.err[-800:])
    if not fixed:
        return ctx.failed(
            "Asked to fix a typo in a file under docs/, the job did not change it.", evidence
        )
    if token in run.sent_text():
        leaked = [
            f"{t} {i.get('command') or i.get('file_path') or i.get('pattern')}"
            for (t, i), r in zip(ATTEMPTS, results, strict=False)
            if token in r
        ] or ["the conversation"]
        return ctx.failed(
            f"The publishing token was sent to the model, through: {', '.join(leaked)}.", evidence
        )
    return ctx.passed("None of the ways the model tried to read the token got it.", evidence)
