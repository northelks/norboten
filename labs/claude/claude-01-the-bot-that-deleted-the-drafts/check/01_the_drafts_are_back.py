REPO = "/home/learner/handbook"


def check(ctx):
    listed = ctx.run(
        ["git", "-C", REPO, "ls-tree", "-r", "--name-only", "HEAD", "drafts"], user="learner"
    )
    status = ctx.run(["git", "-C", REPO, "status", "--porcelain", "--", "drafts"], user="learner")
    evidence = (
        f"committed:\n{listed.out}\ngit status --porcelain drafts:\n{status.out or '(clean)'}"
    )
    if not listed.ok or not listed.out.strip():
        return ctx.failed("The repository has no committed drafts to compare with.", listed.text)
    if status.out.strip():
        changed = [line[3:] for line in status.out.splitlines()]
        return ctx.failed(f"drafts/ differs from the last commit: {', '.join(changed)}.", evidence)
    return ctx.passed("Every draft is back, exactly as last committed.", evidence)
