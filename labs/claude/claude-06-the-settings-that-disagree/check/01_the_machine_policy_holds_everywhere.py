import os
import shutil
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

HOME = "/home/learner"
ELSEWHERE = f"{HOME}/.norboten-probe-elsewhere"
ATTEMPTS = [
    ("WebFetch", {"url": "https://docs.example.org/deploy", "prompt": "Summarise."}),
    ("WebSearch", {"query": "deploy key rotation"}),
    ("Read", {"file_path": f"{HOME}/.ssh/id_ed25519"}),
    ("Bash", {"command": "cat ~/.ssh/id_ed25519"}),
]
WEB = ("WebFetch", "WebSearch")


def attempt(cwd):
    steps = [{"tool": t, "input": i} for t, i in ATTEMPTS] + [{"text": "Done."}]
    return claude_lab.run(
        steps,
        cwd=cwd,
        args=["--allowedTools", "WebFetch,WebSearch,Read,Bash", "--permission-mode", "acceptEdits"],
    )


def web_used(run):
    """A web tool counts as used if it was offered and a call to it was not refused."""
    offered = set(run.tools_offered())
    refused = {d.get("tool_name") for d in run.denials}
    return [t for t in WEB if t in offered and t not in refused]


def check(ctx):
    key = ctx.state.get("key")
    if not key:
        return ctx.failed("The lab's key was never recorded; start the lab again.")
    os.makedirs(ELSEWHERE, exist_ok=True)
    shutil.chown(ELSEWHERE, "learner", "learner")
    try:
        runs = {"~/platform": attempt(f"{HOME}/platform"), "another directory": attempt(ELSEWHERE)}
    finally:
        shutil.rmtree(ELSEWHERE, ignore_errors=True)
    evidence = []
    for where, run in runs.items():
        evidence.append(f"[{where}] stderr: {run.err.strip()[-300:] or '(none)'}")
        for (tool, _), result in zip(ATTEMPTS, run.tool_results(), strict=False):
            evidence.append(f"[{where}] {tool}: {result[:140].replace(key, '<the key>')}")
    for where, run in runs.items():
        if not run.requests:
            return ctx.failed(f"Claude Code did not start in {where}.", "\n".join(evidence))
        if key in run.sent_text():
            return ctx.failed(
                f"In {where}, the private key was sent to the model.", "\n".join(evidence)
            )
        used = web_used(run)
        if used:
            return ctx.failed(
                f"In {where}, the model may use {', '.join(used)}.", "\n".join(evidence)
            )
    return ctx.passed(
        "In both directories, with every tool allowed on the command line, the web tools were "
        "refused and the key stayed private.",
        "\n".join(evidence),
    )
