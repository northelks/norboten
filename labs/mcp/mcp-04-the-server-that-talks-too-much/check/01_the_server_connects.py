import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

HOME = "/home/learner"


def check(ctx):
    steps = [{"tool": "mcp__metrics__get_load", "input": {}}, {"text": "Done."}]
    run = claude_lab.run(steps, cwd=f"{HOME}/ops", command=[f"{HOME}/bin/health-check"])
    offered = run.tools_offered()
    results = run.tool_results()
    said = results[0] if results else ""
    evidence = f"tools offered: {', '.join(offered) or 'none'}\nget_load: {said[:300]}"
    if "mcp__metrics__get_load" not in offered:
        return ctx.failed(
            "Claude Code never got the metrics server's tools: it did not connect.", evidence
        )
    if "load " not in said:
        return ctx.failed("get_load was offered but did not answer.", evidence)
    return ctx.passed("The server connected and get_load answered the job.", evidence)
