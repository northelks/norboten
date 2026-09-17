import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

REPO = "/home/learner/support-digest"
TOOL = "mcp__tickets__list_tickets"


def check(ctx):
    steps = [{"tool": TOOL, "input": {}}, {"text": "Done."}]
    run = claude_lab.run(steps, cwd=REPO, command=["/home/learner/bin/support-digest"])
    results = run.tool_results()
    said = results[0] if results else ""
    evidence = f"{TOOL}: {said[:300]}\ndenials: {[d.get('tool_name') for d in run.denials]}"
    if not results:
        return ctx.failed("The job never got as far as calling a tool.", evidence + run.err[-600:])
    if "No such tool available" in said:
        return ctx.failed(f"{TOOL} does not exist in the job's session.", evidence)
    if "Permission to use" in said or any(d.get("tool_name") == TOOL for d in run.denials):
        return ctx.failed(f"The job is not allowed to call {TOOL}.", evidence)
    return ctx.passed(f"The job called {TOOL} without being refused.", evidence)
