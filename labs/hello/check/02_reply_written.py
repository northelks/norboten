import os


def check(ctx):
    home = ctx.learner_home()
    path = os.path.join(home, "reply.txt")
    if not os.path.isfile(path):
        return ctx.failed(f"There is no reply.txt in {home}.")
    with open(path) as f:
        reply = f.read().strip()
    if reply != ctx.state["secret"]:
        return ctx.failed("reply.txt does not contain the secret word, alone.", f"found: {reply!r}")
    return ctx.passed("Your reply has the right word.")
