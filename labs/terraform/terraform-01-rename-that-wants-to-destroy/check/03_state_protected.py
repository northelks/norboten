import glob
import os
import stat


def check(ctx):
    files = sorted(glob.glob("/srv/infra/terraform.tfstate*"))
    if not files:
        return ctx.failed("There is no state file in /srv/infra.")
    lines, loose = [], []
    for path in files:
        st = os.stat(path)
        mode = stat.S_IMODE(st.st_mode)
        lines.append(f"{path}: mode {mode:04o}, uid {st.st_uid}")
        if mode & 0o077 or st.st_uid != 0:
            loose.append(path)
    evidence = "\n".join(lines)
    if loose:
        return ctx.failed("A state file can be read by accounts other than root.", evidence)
    return ctx.passed("Only root can read the state.", evidence)
