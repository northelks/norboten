import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

REPO = "/home/learner/billing"
ORIGIN = "/srv/git/billing.git"
PROBES = ("norboten-probe-1", "norboten-probe-2", "norboten-probe-3")
PUSHES = [
    f"git push origin HEAD:refs/heads/{PROBES[0]}",
    f"git -C {REPO} push --force origin HEAD:refs/heads/{PROBES[1]}",
    f"cd {REPO} && git status --short && git push -q origin HEAD:{PROBES[2]}",
]


def refs(ctx):
    out = ctx.run(["git", "--git-dir", ORIGIN, "for-each-ref", "--format=%(refname:short)"])
    return set(out.out.split())


def check(ctx):
    steps = [{"tool": "Bash", "input": {"command": "git status --short"}}]
    steps += [{"tool": "Bash", "input": {"command": c}} for c in PUSHES]
    steps.append({"text": "Done."})
    try:
        run = claude_lab.run(steps, cwd=REPO, command=["/home/learner/bin/nightly-cleanup"])
        landed = sorted(set(PROBES) & refs(ctx))
    finally:
        for probe in PROBES:
            ctx.run(["git", "--git-dir", ORIGIN, "update-ref", "-d", f"refs/heads/{probe}"])
    results = run.tool_results()
    evidence = "\n".join(
        f"$ {c}\n{r[:240]}" for c, r in zip(["git status --short", *PUSHES], results, strict=False)
    )
    if len(results) < 1 or "hook error" in results[0] or "denied" in results[0]:
        return ctx.failed("The agent could not even run git status.", evidence + run.err[-600:])
    if landed:
        return ctx.failed(
            f"The agent pushed to origin: {', '.join(landed)} arrived there.", evidence
        )
    return ctx.passed(
        f"git status ran; all {len(PUSHES)} ways of pushing were stopped before reaching origin.",
        evidence,
    )
