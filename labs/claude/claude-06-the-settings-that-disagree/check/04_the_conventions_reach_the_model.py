import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

REPO = "/home/learner/platform"


def check(ctx):
    nonce = ctx.state.get("nonce")
    if not nonce:
        return ctx.failed("The lab's conventions were never recorded; start the lab again.")
    run = claude_lab.run([{"text": "Hello."}], cwd=REPO)
    if not run.requests:
        return ctx.failed("Claude Code did not start in ~/platform.", run.err[-600:])
    sent = run.sent_text()
    evidence = (
        f"CLAUDE.md reached the model: {'infrastructure scripts' in sent.lower()}\n"
        f"conventions (rev {nonce}) reached the model: {f'rev {nonce}' in sent}"
    )
    if f"rev {nonce}" not in sent:
        return ctx.failed(
            "The model is sent CLAUDE.md without the conventions it imports.", evidence
        )
    return ctx.passed("The conventions reach the model with CLAUDE.md.", evidence)
