import json
import secrets
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

REPO = "/home/learner/payments"


def delegated(ctx):
    """Run the job with a model that asks for the reviewer; return the run and its requests."""
    marker = f"norboten-review-{secrets.token_hex(4)}"
    steps = [
        {
            "tool": "Agent",
            "input": {
                "subagent_type": "security-reviewer",
                "description": "Pre-merge security review",
                "prompt": f"Review the diff for security problems. ({marker})",
            },
        },
        {"text": "Review finished."},
    ]
    run = claude_lab.run(steps, cwd=REPO, command=["/home/learner/bin/review-diff"])
    mine = [r for r in run.requests if marker in json.dumps(r["messages"][:1])]
    return run, mine


def check(ctx):
    run, reviewer = delegated(ctx)
    results = run.tool_results()
    evidence = f"model requests: {len(run.requests)}\n" + "\n".join(r[:300] for r in results)
    if not run.requests:
        return ctx.failed("The job never reached the model.", run.err[-800:] or run.out[-800:])
    if not reviewer:
        said = results[0].splitlines()[0][:200] if results else "nothing"
        return ctx.failed(
            "The model asked for the security-reviewer and no subagent ran. "
            f"Claude Code said: {said}",
            evidence,
        )
    return ctx.passed(
        f"The security-reviewer subagent ran the review ({len(reviewer)} request(s) of its own).",
        evidence,
    )
