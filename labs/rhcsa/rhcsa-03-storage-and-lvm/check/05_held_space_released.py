import os


def check(ctx):
    held = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            fds = os.listdir(f"/proc/{pid}/fd")
        except OSError:
            continue
        for fd in fds:
            try:
                target = os.readlink(f"/proc/{pid}/fd/{fd}")
            except OSError:
                continue
            if target.startswith("/var/lib/app/") and target.endswith("(deleted)"):
                comm = (ctx.read(f"/proc/{pid}/comm") or "?").strip()
                held.append(f"pid {pid} ({comm}) -> {target}")
    if held:
        return ctx.failed("A process holds a deleted file on /var/lib/app.", "\n".join(held))
    return ctx.passed("No deleted files are held open on /var/lib/app.")
