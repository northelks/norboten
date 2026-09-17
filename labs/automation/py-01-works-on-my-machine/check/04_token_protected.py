import os
import pwd
import stat


def check(ctx):
    path = "/etc/etl/token"
    try:
        st = os.stat(path)
    except OSError:
        return ctx.failed("The token file is gone.")
    mode = stat.S_IMODE(st.st_mode)
    owner = pwd.getpwuid(st.st_uid).pw_name
    evidence = f"{path}: mode {mode:04o}, owner {owner}"
    if mode & 0o077:
        return ctx.failed("Accounts other than the owner can read the token.", evidence)
    if owner != "etl":
        return ctx.failed("The token is not owned by the account that uses it.", evidence)
    return ctx.passed("Only etl can read the token.", evidence)
