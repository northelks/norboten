import re


def check(ctx):
    # The data directory must be granted in the profile itself — not by widening it to
    # everything, and not by moving the data somewhere the profile already allowed.
    text = ctx.read("/etc/apparmor.d/usr.local.bin.notes-app") or ""
    rules = [line.strip() for line in text.splitlines() if not line.strip().startswith("#")]
    if any(re.match(r"^/\*{1,2}[\s,]", r) for r in rules):
        return ctx.failed("The notes profile grants access to the whole filesystem.", text)
    if not any(r.startswith("/srv/notes/") for r in rules):
        return ctx.failed("The notes profile does not mention the notes data directory.", text)
    return ctx.passed("The profile grants notes its data directory, and only that.", text)
