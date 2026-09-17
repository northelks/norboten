import json
import os
import sys
import tempfile

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

REPO = "/home/learner/site"
EVENT = {"action": "opened", "issue": {"number": 8, "title": "Typo on /pricing", "body": "teh"}}


def check(ctx):
    scratch = tempfile.mkdtemp(prefix="norboten-probe-", dir="/tmp")
    os.chmod(scratch, 0o777)
    event = os.path.join(scratch, "event.json")
    with open(event, "w") as f:
        json.dump(EVENT, f)
    steps = [{"tool": "StructuredOutput", "input": {"label": "bug"}}, {"text": "Labelled."}]
    run = claude_lab.run(
        steps,
        cwd=REPO,
        command="sh ci/triage.sh",
        env={"GITHUB_EVENT_PATH": event, "RUNNER_TEMP": scratch},
        timeout=45,
    )
    if not run.requests:
        return ctx.failed("The script never reached the model.", run.err[-600:] or run.out[-600:])
    first = run.requests[0]
    tools = sorted(set(first["tools"]))
    printed = run.out.strip().splitlines()[-1] if run.out.strip() else ""
    evidence = f"model: {first['model']}\ntools offered: {tools}\nthe script printed: {printed!r}"
    if "haiku" not in first["model"]:
        return ctx.failed(f"The run asks for {first['model']}.", evidence)
    extra = [t for t in tools if t != "StructuredOutput"]
    if extra:
        return ctx.failed(f"The model is offered tools: {', '.join(extra)}.", evidence)
    if printed != "bug":
        return ctx.failed(
            "The model answered with the label bug as structured output, and the script did not "
            "print bug.",
            evidence,
        )
    return ctx.passed("Haiku, no tools, and the label read from structured output.", evidence)
