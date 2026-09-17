import pwd


def _shows(ctx, prop):
    return ctx.run(["systemctl", "show", "partner-sync.service", "-p", prop, "--value"]).out.strip()


def check(ctx):
    user = _shows(ctx, "User") or "root"
    unit = ctx.run(["systemctl", "cat", "partner-sync.service"]).out
    evidence = f"User={user}\n{unit}"
    if user == "root":
        return ctx.failed("partner-sync.service still runs as root.", evidence)
    try:
        entry = pwd.getpwnam(user)
    except KeyError:
        return ctx.failed(f"The service names a user that does not exist: {user}.", evidence)
    evidence += f"\n{entry.pw_name}:{entry.pw_uid}:{entry.pw_dir}:{entry.pw_shell}"
    if entry.pw_uid >= 1000:
        return ctx.failed(f"{user} is an ordinary account, not a system account.", evidence)
    if entry.pw_shell not in ("/usr/sbin/nologin", "/sbin/nologin", "/bin/false", "/usr/bin/false"):
        return ctx.failed(f"{user} can be logged in to ({entry.pw_shell}).", evidence)
    shadow = ctx.run(["passwd", "-S", user]).out.strip()
    if " P " in f" {shadow} ":
        return ctx.failed(f"{user} has a usable password.", evidence + f"\n{shadow}")
    return ctx.passed(f"The sync runs as the system account {user}.", evidence + f"\n{shadow}")
