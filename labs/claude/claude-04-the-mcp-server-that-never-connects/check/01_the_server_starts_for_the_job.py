import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

REPO = "/home/learner/support-digest"


def check(ctx):
    run = claude_lab.run(
        [{"text": "Nothing to do."}], cwd=REPO, command=["/home/learner/bin/support-digest"]
    )
    if not run.requests:
        return ctx.failed("The job never reached the model.", run.err[-800:] or run.out[-800:])
    offered = run.tools_offered()
    mcp = [t for t in offered if t.startswith("mcp__")]
    evidence = f"tools offered to the model: {', '.join(offered)}"
    if not any(t.startswith("mcp__tickets__") for t in mcp):
        return ctx.failed("The model was offered no tools from the tickets server.", evidence)
    return ctx.passed(
        f"The tickets server started; the model was offered {', '.join(mcp)}.", evidence
    )
