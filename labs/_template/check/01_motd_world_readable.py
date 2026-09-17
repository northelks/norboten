import os
import stat


def check(ctx):
    path = "/srv/example/motd"
    if not os.path.exists(path):
        return ctx.failed("The welcome message file does not exist any more.")
    mode = stat.S_IMODE(os.stat(path).st_mode)
    evidence = f"{path} mode {mode:04o}"
    if not mode & stat.S_IROTH:
        return ctx.failed("Other users still cannot read the welcome message.", evidence=evidence)
    return ctx.passed("Every user can read the welcome message.", evidence=evidence)
