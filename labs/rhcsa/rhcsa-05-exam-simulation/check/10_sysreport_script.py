import os
import socket


def _expected():
    st = os.statvfs("/")
    free = round(st.f_bavail * 100 / st.f_blocks)
    return socket.gethostname().split(".")[0], os.uname().release, free


def _matches(out):
    lines = [ln.rstrip() for ln in out.strip().splitlines()]
    host, kernel, free = _expected()
    if len(lines) != 3:
        return False
    try:
        got = int(lines[2].removeprefix("root_free: ").removesuffix("%"))
    except ValueError:
        return False
    return (
        lines[0] == f"hostname: {host}"
        and lines[1] == f"kernel: {kernel}"
        and lines[2].startswith("root_free: ")
        and abs(got - free) <= 1
    )


def check(ctx):
    path = "/usr/local/bin/sysreport"
    if not os.access(path, os.X_OK):
        return ctx.failed("/usr/local/bin/sysreport does not exist or is not executable.")
    head = (ctx.read(path) or "").splitlines()[:1]
    if not head or ("bash" not in head[0] and not head[0].endswith("/sh")):
        return ctx.failed("sysreport is not a shell script.", "\n".join(head))
    out = ctx.run([path])
    if out.code != 0 or not _matches(out.out):
        return ctx.failed("sysreport's output does not match the specification.", out.text)
    target = f"/tmp/.norboten-probe-{os.getpid()}"
    try:
        wrote = ctx.run([path, "-o", target])
        if wrote.code != 0 or wrote.out.strip() or not _matches(ctx.read(target) or ""):
            return ctx.failed("sysreport -o FILE does not write the report to FILE.", wrote.text)
    finally:
        if os.path.exists(target):
            os.unlink(target)
    bad = ctx.run([path, "-z"])
    if bad.code != 2 or not bad.err.strip():
        return ctx.failed(
            "An unknown option does not print an error and exit 2.", f"exit {bad.code}\n{bad.text}"
        )
    return ctx.passed("sysreport follows the specification.", out.out)
