def check(ctx):
    swaps = ctx.read("/proc/swaps") or ""
    kib = sum(int(line.split()[2]) for line in swaps.splitlines()[1:] if line.split())
    fstab = ctx.read("/etc/fstab") or ""
    in_fstab = any(
        len(f := ln.split()) >= 3 and f[2] == "swap" and not ln.lstrip().startswith("#")
        for ln in fstab.splitlines()
    )
    evidence = swaps.strip()
    if kib < 200 * 1024:
        return ctx.failed("No swap space is active.", evidence)
    if not in_fstab:
        return ctx.failed("Swap is on, but nothing will turn it on at the next boot.", evidence)
    return ctx.passed(f"{kib // 1024} MiB of swap is active and configured in fstab.", evidence)
