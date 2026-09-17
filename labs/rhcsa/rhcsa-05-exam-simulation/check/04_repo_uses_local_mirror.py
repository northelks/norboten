def check(ctx):
    r = ctx.run(["dnf", "-q", "repolist", "--enabled"], timeout=60)
    ids = [ln.split()[0] for ln in r.out.splitlines()[1:] if ln.strip()]
    if not ids:
        return ctx.failed("No repository is enabled.", r.text)
    info = ctx.run(["dnf", "-q", "repoinfo", "--enabled"], timeout=60).out
    if "/opt/repos/local" not in info:
        return ctx.failed("The enabled repository does not use /opt/repos/local.", info[-1500:])
    if len(ids) > 1:
        return ctx.failed(f"More than one repository is enabled: {', '.join(ids)}.")
    avail = ctx.run(["dnf", "-q", "--cacheonly", "list", "--available", "zsh"], timeout=60)
    if not avail.ok:
        fresh = ctx.run(["dnf", "-q", "makecache"], timeout=60)
        if not fresh.ok:
            return ctx.failed("dnf cannot read the configured repository.", fresh.text[-1000:])
    return ctx.passed(f"Only {ids[0]} is enabled, and it uses the local mirror.")
