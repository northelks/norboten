import secrets
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

HOME = "/home/learner"
JOB = [f"{HOME}/bin/ask-notes"]


def check(ctx):
    marker = f"dotted-{secrets.token_hex(6)}"  # the content; the name must not give it away
    name = f".check-{secrets.token_hex(3)}"
    hidden = f"{HOME}/notes/{name}"
    ctx.write(hidden, f"SECRET={marker}\n", mode=0o600, owner="learner", group="learner")
    steps = [
        {"tool": "mcp__files__list_directory", "input": {"path": f"{HOME}/notes"}},
        {"tool": "mcp__files__read_file", "input": {"path": hidden}},
        {"text": "Done."},
    ]
    try:
        run = claude_lab.run(steps, cwd=f"{HOME}/notes-bot", command=JOB)
    finally:
        ctx.run(["rm", "-f", hidden])
    results = run.tool_results()
    evidence = "\n---\n".join(r[:300] for r in results) or (run.err[-600:] or run.out[-600:])
    if len(results) < 2:
        return ctx.failed("The job never got as far as calling the server.", evidence)
    if name in results[0]:
        return ctx.failed(f"Listing ~/notes showed the dotfile {name}.", evidence)
    if marker in results[1]:
        return ctx.failed(f"The server read the dotfile {name}.", evidence)
    return ctx.passed("Dotfiles in ~/notes are neither listed nor read.", evidence)
