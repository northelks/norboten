HOME = "/home/learner"
REPO = f"{HOME}/handbook-bot"


def check(ctx):
    key = ctx.state.get("key")
    if not key:
        return ctx.failed("The lab's key was never recorded; start the lab again.")
    tracked = ctx.run(["git", "-C", REPO, "ls-files"], user="learner")
    if not tracked.ok:
        return ctx.failed("~/handbook-bot is not a git repository any more.", tracked.text)
    now = [f for f in tracked.out.split() if key in (ctx.read(f"{REPO}/{f}") or "")]
    head = ctx.run(["git", "-C", REPO, "grep", "-l", "-F", key, "HEAD"], user="learner").out.strip()
    evidence = f"tracked files holding the key: {now or 'none'}\nin HEAD: {head or 'none'}"
    if now:
        return ctx.failed(f"The key is in a tracked file: {', '.join(now)}.", evidence)
    if head:
        return ctx.failed("The latest commit still holds the key.", evidence)
    return ctx.passed("No tracked file, and nothing in the latest commit, holds the key.", evidence)
