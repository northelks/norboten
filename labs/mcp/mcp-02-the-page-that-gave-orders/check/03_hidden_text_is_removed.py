import secrets
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

HOME = "/home/learner"
JOB = [f"{HOME}/bin/release-notes"]


def check(ctx):
    name, hidden = secrets.token_hex(3), f"hidden-{secrets.token_hex(6)}"
    page = f"/srv/web/docs.example/notes-{name}.html"
    ctx.write(
        page,
        f"<h1>Release</h1><p>Visible text.</p><!-- {hidden} comment -->"
        f'<div style="display: none">{hidden} div</div><span hidden>{hidden} span</span>',
        mode=0o644,
    )
    steps = [
        {"tool": "mcp__web__fetch_page", "input": {"url": f"https://docs.example/notes-{name}"}},
        {"text": "Done."},
    ]
    try:
        run = claude_lab.run(steps, cwd=f"{HOME}/release", command=JOB)
    finally:
        ctx.run(["rm", "-f", page])
    results = run.tool_results()
    evidence = "\n---\n".join(r[:400] for r in results) or run.err[-600:]
    if not results or "Visible text" not in results[0]:
        return ctx.failed("The page's visible text did not come back.", evidence)
    if hidden in results[0]:
        return ctx.failed("Text hidden from a reader of the page reached the model.", evidence)
    return ctx.passed(
        "Comments and hidden elements are removed; the visible text arrives.", evidence
    )
