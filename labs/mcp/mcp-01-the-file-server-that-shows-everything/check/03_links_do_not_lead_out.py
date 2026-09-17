import os
import secrets
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

HOME = "/home/learner"
JOB = [f"{HOME}/bin/ask-notes"]


def check(ctx):
    marker = f"linked-{secrets.token_hex(6)}"  # the content; the names must not give it away
    name = secrets.token_hex(3)
    target = f"{HOME}/private-{name}"
    link = f"{HOME}/notes/drafts-{name}"
    ctx.write(f"{target}/secret.txt", marker + "\n", owner="learner", group="learner")
    os.symlink(target, link)
    steps = [
        {"tool": "mcp__files__read_file", "input": {"path": f"{link}/secret.txt"}},
        {"text": "Done."},
    ]
    try:
        run = claude_lab.run(steps, cwd=f"{HOME}/notes-bot", command=JOB)
    finally:
        ctx.run(["rm", "-rf", link, target])
    results = run.tool_results()
    evidence = "\n---\n".join(r[:300] for r in results) or (run.err[-600:] or run.out[-600:])
    if not results:
        return ctx.failed("The job never got as far as calling the server.", evidence)
    if marker in results[0]:
        return ctx.failed(
            "A link inside ~/notes led the server to a file outside it, and it read it.", evidence
        )
    return ctx.passed("A link inside ~/notes that leads out of it was refused.", evidence)
