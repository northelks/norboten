def check(ctx):
    groups = ctx.run(["id", "-nG", ctx.learner]).out.split()
    if "wheel" not in groups:
        return ctx.failed(f"{ctx.learner} is not in the administrators' group.", " ".join(groups))
    r = ctx.run(["sudo", "-l", "-U", ctx.learner])
    if "(ALL) ALL" not in r.out and "(ALL : ALL) ALL" not in r.out:
        return ctx.failed(f"{ctx.learner} is in wheel, but sudo does not grant it.", r.text)
    return ctx.passed(f"{ctx.learner} administers the system through wheel.")
