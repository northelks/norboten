def check(ctx):
    line = next(
        (ln for ln in (ctx.read("/etc/shadow") or "").splitlines() if ln.startswith("maria:")), ""
    )
    if not line:
        return ctx.failed("There is no user maria.")
    maxdays = line.split(":")[4]
    chage = ctx.run(["chage", "-l", "maria"]).out
    if maxdays != "90":
        return ctx.failed(
            f"maria's maximum password age is {maxdays or 'unset'}, not 90 days.", chage
        )
    return ctx.passed("maria must change her password every 90 days.", chage)
