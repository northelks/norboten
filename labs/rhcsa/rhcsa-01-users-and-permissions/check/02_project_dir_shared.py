import grp
import os
import stat


def check(ctx):
    path = "/srv/project"
    if not os.path.isdir(path):
        return ctx.failed("/srv/project is gone.")
    st = os.stat(path)
    mode = stat.S_IMODE(st.st_mode)
    group = grp.getgrgid(st.st_gid).gr_name
    evidence = f"{path}: mode {mode:04o}, group {group}"
    if group != "devops":
        return ctx.failed("The shared directory does not belong to the devops group.", evidence)
    if mode & 0o070 != 0o070:
        return ctx.failed("Group members cannot create files in the shared directory.", evidence)
    if not mode & stat.S_ISGID:
        return ctx.failed(
            "New files in the shared directory take their creator's group, not the directory's.",
            evidence,
        )
    return ctx.passed("The shared directory is group-writable and passes its group on.", evidence)
