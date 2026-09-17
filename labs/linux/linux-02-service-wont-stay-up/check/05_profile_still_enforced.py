def check(ctx):
    profiles = ctx.read("/sys/kernel/security/apparmor/profiles")
    if profiles is None:
        return ctx.failed("AppArmor is not active on this system.")
    line = next((p for p in profiles.splitlines() if p.startswith("/usr/local/bin/notes-app ")), "")
    if not line:
        return ctx.failed("The notes AppArmor profile is not loaded.", profiles[-1500:])
    if "(enforce)" not in line:
        return ctx.failed("The notes AppArmor profile is loaded, but not enforcing.", line)
    return ctx.passed("The notes profile is loaded and enforcing.", line)
