def check(ctx):
    r = ctx.run(["rpm", "-q", "tree"])
    if not r.ok:
        return ctx.failed("The tree package is not installed.", r.text)
    return ctx.passed(f"{r.out.strip()} is installed.")
