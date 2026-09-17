def check(ctx):
    # A login shell, as when kmorris logs in: reads /etc/profile and ~/.bash_profile.
    r = ctx.run(["su", "-", "kmorris", "-c", "umask"])
    if not r.ok:
        return ctx.failed("Could not start a login shell for kmorris.", r.text)
    value = r.out.strip().splitlines()[-1] if r.out.strip() else ""
    try:
        mask = int(value, 8)
    except ValueError:
        return ctx.failed("kmorris's login shell reports no umask.", r.text)
    if mask & 0o060:
        return ctx.failed(
            f"Files kmorris creates cannot be read and edited by the group (umask {value}).",
            f"umask in a login shell: {value}",
        )
    return ctx.passed(f"kmorris's files are group-readable and -writable (umask {value}).")
