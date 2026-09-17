"""kmorris exists but is in 'developers' instead of 'devops'."""


def _group(ctx, name):
    if not ctx.run(["getent", "group", name]).ok:
        ctx.run(["groupadd", name], check=True)


def _user(ctx, name, groups):
    if not ctx.run(["id", name]).ok:
        ctx.run(["useradd", "-m", "-s", "/bin/bash", name], check=True)
    ctx.run(["usermod", "-G", groups, name], check=True)


def apply(ctx):
    for g in ("devops", "developers", "ops"):
        _group(ctx, g)
    _user(ctx, "apatel", "devops")
    _user(ctx, "rsingh", "ops")
    _user(ctx, "kmorris", "developers")
