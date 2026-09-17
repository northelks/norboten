REPO = "/home/learner/support-digest"


def check(ctx):
    token = ctx.state.get("token")
    if not token:
        return ctx.failed("The lab's token was never recorded; start the lab again.")
    tracked = ctx.run(["git", "-C", REPO, "ls-files"], user="learner")
    in_head = ctx.run(["git", "-C", REPO, "grep", "-l", "-F", token, "HEAD"], user="learner")
    files = [f for f in tracked.out.split() if token in (ctx.read(f"{REPO}/{f}") or "")]
    evidence = (
        f"tracked files:\n{tracked.out}\ncontaining the token now: {files or 'none'}\n"
        f"in HEAD: {in_head.out.strip() or 'none'}"
    )
    if not tracked.ok:
        return ctx.failed("~/support-digest is not a git repository any more.", tracked.text)
    if files:
        return ctx.failed(f"The token is in a tracked file: {', '.join(files)}.", evidence)
    if in_head.out.strip():
        head = in_head.out.strip().replace("HEAD:", "")
        return ctx.failed(f"The latest commit still contains the token in {head}.", evidence)
    return ctx.passed(
        "No tracked file, and nothing in the latest commit, holds the token.", evidence
    )
