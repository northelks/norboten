import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

HOME = "/home/learner"


def check(ctx):
    ctx.run(["/usr/local/bin/reports-mcp", "restart"])
    ctx.run(["/usr/local/bin/proxy-restart"])
    steps = [{"tool": "mcp__reports__build_report", "input": {}}, {"text": "Done."}]
    run = claude_lab.run(
        steps, cwd=f"{HOME}/ops-report", command=[f"{HOME}/bin/weekly-report"], timeout=150
    )
    results = run.tool_results()
    said = results[0] if results else ""
    evidence = f"tools offered: {', '.join(run.tools_offered())}\nbuild_report: {said[:300]}"
    report = ctx.state.get("report", "?")
    if f"Weekly report {report}" not in said:
        return ctx.failed("The job's build_report call did not bring the report back.", evidence)
    return ctx.passed(f"The job got report {report} through the server.", evidence)
