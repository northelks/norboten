GIB = 1024**3


def check(ctx):
    out = ctx.run(
        ["systemctl", "show", "ollama", "-p", "MemoryMax", "-p", "MemoryPeak", "-p", "NRestarts"]
    ).out
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    evidence = out.strip()
    limit = props.get("MemoryMax", "infinity")
    if not limit.isdigit():
        return ctx.failed("The service has no memory limit.", evidence)
    limit = int(limit)
    if not GIB <= limit <= 2 * GIB:
        return ctx.failed(f"The memory limit is {limit // 1024**2} MiB, outside 1–2 GiB.", evidence)
    peak = props.get("MemoryPeak", "")
    if not peak.isdigit() or int(peak) == 0:
        return ctx.failed(
            "The service has not used any memory yet: it has not loaded a model.", evidence
        )
    if int(peak) > 0.8 * limit:
        return ctx.failed(
            f"Peak memory {int(peak) // 1024**2} MiB is above 80% of the "
            f"{limit // 1024**2} MiB limit.",
            evidence,
        )
    return ctx.passed(f"Limit {limit // 1024**2} MiB; peak {int(peak) // 1024**2} MiB.", evidence)
