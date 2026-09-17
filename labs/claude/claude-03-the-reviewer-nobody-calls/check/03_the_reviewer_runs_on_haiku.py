import json
import secrets
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

REPO = "/home/learner/payments"


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
    main = [r for r in run.requests if r not in reviewer]
    if not reviewer:
        return ctx.failed("No security-reviewer subagent ran, so there is no model to judge.")
    models = sorted({r["model"] for r in reviewer})
    evidence = (
        f"reviewer model: {', '.join(models)}\nmain agent model: "
        f"{', '.join(sorted({r['model'] for r in main})) or 'n/a'}"
    )
    if not all("haiku" in m for m in models):
        return ctx.failed(f"The reviewer asks for {', '.join(models)}, not Haiku.", evidence)
    return ctx.passed(f"The reviewer runs on {models[0]}.", evidence)
