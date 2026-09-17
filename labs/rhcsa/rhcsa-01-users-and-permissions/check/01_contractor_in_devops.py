def check(ctx):
    r = ctx.run(["id", "-nG", "kmorris"])
    if not r.ok:
        return ctx.failed("The kmorris account no longer exists.", r.text)
    groups = set(r.out.split()) - {"kmorris"}
    if "devops" not in groups:
        return ctx.failed("kmorris is not a member of devops.", f"id -nG: {r.out.strip()}")
    extra = groups - {"devops"}
    if extra:
        return ctx.failed(
            f"kmorris is also a member of {', '.join(sorted(extra))}.", f"id -nG: {r.out.strip()}"
        )
    return ctx.passed("kmorris is in devops and no other team.", r.out.strip())
