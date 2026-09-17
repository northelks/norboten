import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

HOME = "/home/learner"
JOB = [f"{HOME}/bin/release-notes"]


def check(ctx):
    steps = [
        {"tool": "mcp__web__fetch_page", "input": {"url": "https://docs.example/changelog"}},
        {"text": "Done."},
    ]
    run = claude_lab.run(steps, cwd=f"{HOME}/release", command=JOB)
    results = run.tool_results()
    evidence = "\n---\n".join(r[:400] for r in results) or run.err[-600:]
    if not results or "Search is faster" not in results[0]:
        return ctx.failed("The changelog did not come back.", evidence)
    if "<untrusted-content" not in results[0]:
        return ctx.failed("The page reaches the model with nothing marking it as data.", evidence)
    return ctx.passed("Fetched pages reach the model marked as untrusted data.", evidence)
