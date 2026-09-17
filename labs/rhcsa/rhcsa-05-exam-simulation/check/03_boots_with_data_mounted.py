import os


def check(ctx):
    for line in (ctx.read("/etc/fstab") or "").splitlines():
        f = line.split()
        if len(f) >= 2 and f[1] == "/data" and not line.lstrip().startswith("#"):
            src = f[0]
            if src.startswith("UUID=") and not os.path.exists(f"/dev/disk/by-uuid/{src[5:]}"):
                return ctx.failed("fstab mounts /data from a UUID that does not exist.", line)
            if src.startswith("/dev/"):
                return ctx.failed("fstab mounts /data by a raw device name.", line)
            break
    else:
        return ctx.failed("fstab has no entry for /data.")
    if not os.path.ismount("/data"):
        return ctx.failed("/data is not mounted.")
    if ctx.phase == "post_reboot":
        state = ctx.run(["systemctl", "is-system-running"]).out.strip()
        if state not in ("running", "degraded"):
            return ctx.failed(f"The system did not finish booting ({state}).")
    return ctx.passed("The system boots with /data mounted by UUID.")
