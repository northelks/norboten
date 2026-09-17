import os
import stat


def check(ctx):
    path = "/srv/hello/message.txt"
    if not os.path.isfile(path):
        return ctx.failed("The message file is gone.")
    st = os.stat(path)
    evidence = f"{path}: mode {stat.S_IMODE(st.st_mode):04o}, owner uid {st.st_uid}"
    if not st.st_mode & stat.S_IROTH:
        return ctx.failed("Users other than the owner still cannot read the message.", evidence)
    return ctx.passed("Everyone can read the message.", evidence)
