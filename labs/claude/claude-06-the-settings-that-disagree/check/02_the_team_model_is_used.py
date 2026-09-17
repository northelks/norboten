import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

REPO = "/home/learner/platform"


def check(ctx):
    run = claude_lab.run([{"text": "Hello."}], cwd=REPO)
    if not run.requests:
        return ctx.failed("Claude Code did not start in ~/platform.", run.err[-600:])
    model = run.requests[0]["model"]
    evidence = f"requested model: {model}\n{run.err.strip()[-300:]}"
    if "haiku" not in model:
        return ctx.failed(
            f"A session in ~/platform that names no model asks for {model}.", evidence
        )
    return ctx.passed(f"A session in ~/platform runs on {model}.", evidence)
