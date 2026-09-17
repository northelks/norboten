import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

HOME = "/home/learner"


def check(ctx):
    steps = [{"tool": "mcp__docs__search", "input": {"query": "rotation"}}, {"text": "Done."}]
    run = claude_lab.run(steps, cwd=f"{HOME}/handbook-bot", command=[f"{HOME}/bin/ask-handbook"])
    results = run.tool_results()
    said = results[0] if results else ""
    evidence = f"search: {said[:300]}\n{run.err[-300:]}"
    if "[handbook edition 3]" in said:
        return ctx.passed("The job's answers come from edition 3 of the handbook.", evidence)
    if "[handbook edition 1]" in said:
        return ctx.failed("The job is answered from edition 1, last year's handbook.", evidence)
    return ctx.failed("The docs server did not answer the job.", evidence)
