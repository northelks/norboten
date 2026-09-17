import os
import pwd
import stat

TOKEN_FILE = "/etc/partner/token"


def check(ctx):
    if not os.path.exists(TOKEN_FILE):
        return ctx.failed(f"{TOKEN_FILE} does not exist any more.")
    info = os.stat(TOKEN_FILE)
    mode = stat.S_IMODE(info.st_mode)
    owner = pwd.getpwuid(info.st_uid).pw_name
    as_learner = ctx.run(["cat", TOKEN_FILE], user=ctx.learner, timeout=20)
    listing = ctx.run(["ls", "-l", TOKEN_FILE, "/etc/partner"]).out
    evidence = (
        f"mode {mode:04o}, owner {owner}\n{listing}\nas {ctx.learner}: exit {as_learner.code}"
    )
    if mode & 0o077:
        return ctx.failed("The token file can be read by more than its owner.", evidence)
    if as_learner.ok:
        return ctx.failed(f"{ctx.learner} can read the token file.", evidence)
    return ctx.passed("The token file is readable by its owner only.", evidence)
