import secrets
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

HOME = "/home/learner"
JOB = [f"{HOME}/bin/ask-notes"]


def check(ctx):
    marker = f"handover-{secrets.token_hex(4)}"
    note = f"{HOME}/notes/{marker}.md"
    runbook = f"{HOME}/notes/runbook.md"
    before = ctx.read(runbook)
    ctx.write(note, f"# Handover\n\n{marker}\n", owner="learner", group="learner")
    steps = [
        {"tool": "mcp__files__list_directory", "input": {"path": f"{HOME}/notes"}},
        {"tool": "mcp__files__read_file", "input": {"path": note}},
        {"tool": "mcp__files__write_file", "input": {"path": runbook, "content": "# gone\n"}},
        {"text": "Done."},
    ]
    try:
        run = claude_lab.run(steps, cwd=f"{HOME}/notes-bot", command=JOB)
        after = ctx.read(runbook)
    finally:
        ctx.run(["rm", "-f", note])
        if before is not None and ctx.read(runbook) != before:
            ctx.write(runbook, before, owner="learner", group="learner")
    results = run.tool_results()
    evidence = "\n---\n".join(r[:300] for r in results) or (run.err[-600:] or run.out[-600:])
    if not any(t.startswith("mcp__files__") for t in run.tools_offered()):
        return ctx.failed("The files server's tools were not offered to the model.", evidence)
    if len(results) < 2 or marker not in results[1]:
        return ctx.failed("A note in ~/notes could not be read through the server.", evidence)
    if f"{marker}.md" not in results[0]:
        return ctx.failed("Listing ~/notes did not show a note that is in it.", evidence)
    if after != before:
        return ctx.failed("The model rewrote ~/notes/runbook.md through the server.", evidence)
    return ctx.passed(
        "Notes are listed and read through the server, and cannot be changed.", evidence
    )
