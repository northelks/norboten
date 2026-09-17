import grp
import os
import stat


def check(ctx):
    path = "/srv/audit"
    if not os.path.isdir(path):
        return ctx.failed("/srv/audit does not exist.")
    st = os.stat(path)
    mode = stat.S_IMODE(st.st_mode)
    group = grp.getgrgid(st.st_gid).gr_name
    evidence = f"{path}: mode {mode:04o}, group {group}"
    if group != "auditors":
        return ctx.failed("/srv/audit does not belong to auditors.", evidence)
    if mode & 0o070 != 0o070 or not mode & stat.S_ISGID:
        return ctx.failed("Members cannot share files there as the task requires.", evidence)
    if mode & 0o007:
        return ctx.failed("Users outside auditors can still get into /srv/audit.", evidence)
    return ctx.passed("/srv/audit is a private shared directory for auditors.", evidence)
