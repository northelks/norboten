import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

REPO = "/home/learner/support-digest"
TOOL = "mcp__tickets__list_tickets"


def check(ctx):
    ticket = ctx.state.get("ticket")
    if not ticket:
        return ctx.failed("The lab's queue was never recorded; start the lab again.")
    steps = [{"tool": TOOL, "input": {}}, {"text": "Done."}]
    run = claude_lab.run(steps, cwd=REPO, command=["/home/learner/bin/support-digest"])
    results = run.tool_results()
    said = results[0] if results else ""
    evidence = f"{TOOL}: {said[:300]}"
    if ticket in said:
        return ctx.passed(f"The tool returned the open queue, {ticket} included.", evidence)
    if "unauthorized" in said:
        return ctx.failed(
            "The tickets server refused the call: the token it received is wrong.", evidence
        )
    return ctx.failed("The tool did not return the queue.", evidence)
