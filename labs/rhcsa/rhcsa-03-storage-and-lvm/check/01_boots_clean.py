import os

PSEUDO = {"proc", "sysfs", "tmpfs", "devpts", "none", "swap", "nfs", "nfs4", "cifs", "efivarfs"}


def _source_exists(src):
    if src.startswith("UUID="):
        return os.path.exists(f"/dev/disk/by-uuid/{src[5:]}")
    if src.startswith("LABEL="):
        return os.path.exists(f"/dev/disk/by-label/{src[6:]}")
    if src.startswith("/dev/"):
        return os.path.exists(src)
    return True


def check(ctx):
    fstab = ctx.read("/etc/fstab") or ""
    missing = []
    for line in fstab.splitlines():
        fields = line.split()
        if len(fields) < 3 or line.lstrip().startswith("#") or fields[2] in PSEUDO:
            continue
        if not _source_exists(fields[0]):
            missing.append(line)
    if missing:
        return ctx.failed(
            "fstab refers to a device the system cannot find — boot will stop there.",
            "\n".join(missing),
        )
    verify = ctx.run(["findmnt", "--verify", "--tab-file", "/etc/fstab"])
    if verify.code != 0:
        return ctx.failed("fstab does not verify.", verify.text)
    if not os.path.ismount("/var/lib/app"):
        return ctx.failed("/var/lib/app is not mounted.")
    if ctx.phase == "post_reboot":
        state = ctx.run(["systemctl", "is-system-running"]).out.strip()
        if state not in ("running", "degraded"):
            return ctx.failed(
                f"The system did not finish booting (state: {state}).",
                ctx.run(["systemctl", "--failed", "--no-pager"]).text,
            )
    return ctx.passed("fstab verifies and /var/lib/app is mounted.", verify.text)
