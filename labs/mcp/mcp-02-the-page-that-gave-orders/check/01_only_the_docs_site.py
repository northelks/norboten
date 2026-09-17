import secrets
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

HOME = "/home/learner"
JOB = [f"{HOME}/bin/release-notes"]


def check(ctx):
    secret = f"AKIA{secrets.token_hex(8).upper()}"
    name = secrets.token_hex(3)
    inside = f"/srv/web/metadata.internal/latest/check-{name}.html"
    ctx.write(inside, f"AccessKeyId={secret}\n", mode=0o644)
    steps = [
        {"tool": "mcp__web__fetch_page", "input": {"url": "https://docs.example/changelog"}},
        {
            "tool": "mcp__web__fetch_page",
            "input": {"url": f"http://metadata.internal/latest/check-{name}"},
        },
        {"text": "Done."},
    ]
    try:
        run = claude_lab.run(steps, cwd=f"{HOME}/release", command=JOB)
    finally:
        ctx.run(["rm", "-f", inside])
    results = run.tool_results()
    evidence = "\n---\n".join(r[:300] for r in results) or (run.err[-600:] or run.out[-600:])
    if len(results) < 2:
        return ctx.failed("The job never got as far as fetching two pages.", evidence)
    if "Search is faster" not in results[0]:
        return ctx.failed("The docs site's changelog could not be fetched.", evidence)
    if secret in results[1]:
        return ctx.failed(
            "The server fetched http://metadata.internal/ for the model: any host will do.",
            evidence,
        )
    return ctx.passed("The docs site is fetched; an internal host is refused.", evidence)
