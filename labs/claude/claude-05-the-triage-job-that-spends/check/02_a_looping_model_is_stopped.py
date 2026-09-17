import json
import os
import sys
import tempfile
import time

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

REPO = "/home/learner/site"
LIMIT = 5
ASKS = 40
EVENT = {
    "action": "opened",
    "issue": {"number": 7, "title": "Search is slow", "body": "Takes 9 s."},
}


def check(ctx):
    scratch = tempfile.mkdtemp(prefix="norboten-probe-", dir="/tmp")
    os.chmod(scratch, 0o777)
    event = os.path.join(scratch, "event.json")
    with open(event, "w") as f:
        json.dump(EVENT, f)
    # forty turns of "let me look first" stand in for a model that never finishes: an endless script
    # would run thousands of instant turns and exhaust the container's memory before any timeout
    steps = [
        {"text": "Let me look first.", "tool": "Read", "input": {"file_path": f"{REPO}/README.md"}}
    ] * ASKS
    steps.append({"text": "question"})
    started = time.monotonic()
    run = claude_lab.run(
        steps,
        cwd=REPO,
        command="sh ci/triage.sh",
        env={"GITHUB_EVENT_PATH": event, "RUNNER_TEMP": scratch},
        timeout=45,
    )
    seconds = time.monotonic() - started
    evidence = (
        f"model requests: {len(run.requests)} in {seconds:.1f} s, exit {run.code}\n{run.err[-400:]}"
    )
    if not run.requests:
        return ctx.failed("The script never reached the model.", evidence + run.out[-400:])
    if run.code == 124:
        return ctx.failed(
            f"After {seconds:.0f} s and {len(run.requests)} requests the run was still going.",
            evidence,
        )
    if len(run.requests) > LIMIT:
        return ctx.failed(
            f"The run went on for {len(run.requests)} model requests, until the model itself "
            "stopped; a label takes one.",
            evidence,
        )
    return ctx.passed(
        f"A model that kept asking for more was stopped after {len(run.requests)} request(s).",
        evidence,
    )
