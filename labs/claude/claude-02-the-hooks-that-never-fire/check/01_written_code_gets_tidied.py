import os
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

REPO = "/home/learner/billing"
PROBE = f"{REPO}/app/.norboten-probe-tidy.py"


def check(ctx):
    steps = [
        {"tool": "Write", "input": {"file_path": PROBE, "content": "def total():\n\treturn 0\n"}},
        {"tool": "Read", "input": {"file_path": PROBE}},
        {
            "tool": "Edit",
            "input": {
                "file_path": PROBE,
                "old_string": "return 0",
                "new_string": "if True:\n\t\treturn 1",
            },
        },
        {"text": "Done."},
    ]
    try:
        run = claude_lab.run(steps, cwd=REPO, command=["/home/learner/bin/nightly-cleanup"])
        text = ctx.read(PROBE)
    finally:
        if os.path.exists(PROBE):
            os.remove(PROBE)
    results = run.tool_results()
    evidence = f"file after the run: {text!r}\n" + "\n".join(r[:200] for r in results)
    if text is None or "return 1" not in text:
        return ctx.failed(
            "The agent's Write and Edit did not both land.", evidence + run.err[-600:]
        )
    dirty = [n for n, line in enumerate(text.splitlines(), 1) if "\t" in line]
    if dirty:
        return ctx.failed(
            f"A Python file the agent wrote and edited is still indented with tabs "
            f"(line {dirty[0]}).",
            evidence,
        )
    return ctx.passed("What the agent wrote and edited came out indented with spaces.", evidence)
