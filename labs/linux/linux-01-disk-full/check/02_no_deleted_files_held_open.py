import os


def check(ctx):
    held = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        fd_dir = f"/proc/{pid}/fd"
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                target = os.readlink(f"{fd_dir}/{fd}")
            except OSError:
                continue
            if target.startswith("/var/log/app/") and target.endswith("(deleted)"):
                comm = (ctx.read(f"/proc/{pid}/comm") or "?").strip()
                held.append(f"pid {pid} ({comm}) fd {fd} -> {target}")
    if held:
        return ctx.failed(
            "A running process still holds a deleted file on the log filesystem.", "\n".join(held)
        )
    return ctx.passed("No deleted files are held open on the log filesystem.")
