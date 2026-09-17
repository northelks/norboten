import json
import secrets
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

REPO = "/home/learner/payments"
READING = {"Read", "Grep", "Glob"}


def check(ctx):
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
    reviewer = [r for r in run.requests if marker in json.dumps(r["messages"][:1])]
    if not reviewer:
        return ctx.failed("No security-reviewer subagent ran, so it has no tools to judge.")
    offered = sorted(set(reviewer[0]["tools"]))
    evidence = f"tools offered to the reviewer: {', '.join(offered) or 'none'}"
    extra = [t for t in offered if t not in READING]
    if extra:
        return ctx.failed(
            f"The reviewer is offered tools beyond reading: {', '.join(extra)}.", evidence
        )
    if "Read" not in offered:
        return ctx.failed("The reviewer cannot even read files.", evidence)
    return ctx.passed(f"The reviewer is offered only {', '.join(offered)}.", evidence)
