import warnings

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import crypt


def check(ctx):
    shadow = ctx.read("/etc/shadow") or ""
    line = next((ln for ln in shadow.splitlines() if ln.startswith("root:")), "")
    hashed = line.split(":")[1] if line else ""
    if not hashed or hashed[0] in "!*":
        return ctx.failed("root has no usable password.")
    if crypt.crypt("Rhcsa-Lab5!", hashed) != hashed:
        return ctx.failed("The root password is not the one the task asks for.")
    return ctx.passed("The root password is set as required.")
