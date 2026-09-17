import secrets
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

HOME = "/home/learner"
JOB = [f"{HOME}/bin/ask-notes"]


def check(ctx):
    marker = f"private-{secrets.token_hex(6)}"  # the content; the name must not give it away
    elsewhere = f"{HOME}/.config/notes-bot/check-{secrets.token_hex(3)}"
    ctx.write(elsewhere, marker + "\n", mode=0o600, owner="learner", group="learner")
    steps = [
        {"tool": "mcp__files__read_file", "input": {"path": elsewhere}},
        {"tool": "mcp__files__read_file", "input": {"path": "/etc/passwd"}},
        {"text": "Done."},
    ]
    try:
        run = claude_lab.run(steps, cwd=f"{HOME}/notes-bot", command=JOB)
    finally:
        ctx.run(["rm", "-f", elsewhere])
    results = run.tool_results()
    evidence = "\n---\n".join(r[:300] for r in results) or (run.err[-600:] or run.out[-600:])
    if len(results) < 2:
        return ctx.failed("The job never got as far as calling the server.", evidence)
    if marker in results[0]:
        return ctx.failed(f"The server read {elsewhere}, outside ~/notes.", evidence)
    if "root:" in results[1]:
        return ctx.failed("The server read /etc/passwd.", evidence)
    return ctx.passed("Files outside ~/notes were refused by the server.", evidence)
