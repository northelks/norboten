import os


def check(ctx):
    path = "/var/log/app"
    if not os.path.ismount(path):
        return ctx.failed("Nothing is mounted at /var/log/app.")
    st = os.statvfs(path)
    free = st.f_bavail / st.f_blocks
    evidence = ctx.run(["df", "-h", path]).out
    if free < 0.5:
        return ctx.failed(f"The log filesystem has only {free:.0%} free.", evidence)
    return ctx.passed(f"The log filesystem has {free:.0%} free.", evidence)
