REPO = "/home/learner/platform"
PERSONAL = (".claude/settings.local.json", "CLAUDE.local.md")


def check(ctx):
    tracked = ctx.run(["git", "-C", REPO, "ls-files"], user="learner")
    if not tracked.ok:
        return ctx.failed("~/platform is not a git repository any more.", tracked.text)
    listed = set(tracked.out.split())
    evidence = [f"tracked: {', '.join(sorted(listed))}"]
    committed = [p for p in PERSONAL if p in listed]
    if committed:
        return ctx.failed(f"The repository tracks {', '.join(committed)}.", "\n".join(evidence))
    unignored = []
    for path in PERSONAL:
        r = ctx.run(["git", "-C", REPO, "check-ignore", "-q", "--no-index", path], user="learner")
        evidence.append(f"git check-ignore {path}: {'ignored' if r.ok else 'not ignored'}")
        if not r.ok:
            unignored.append(path)
    if unignored:
        return ctx.failed(f"git would pick up {', '.join(unignored)} again.", "\n".join(evidence))
    return ctx.passed(
        "Personal settings are neither tracked nor able to be added by accident.",
        "\n".join(evidence),
    )
