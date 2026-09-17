import glob
import re

SETTING = re.compile(r"^\s*net[./]ipv4[./]ip_forward\s*=\s*(\S+)")


def check(ctx):
    lines = []
    for path in [*sorted(glob.glob("/etc/sysctl.d/*.conf")), "/etc/sysctl.conf"]:
        for n, line in enumerate((ctx.read(path) or "").splitlines(), 1):
            if SETTING.match(line):
                lines.append(f"{path}:{n}: {line.strip()}")
    runtime = ctx.run(["sysctl", "-n", "net.ipv4.ip_forward"]).out.strip()
    evidence = f"runtime net.ipv4.ip_forward = {runtime}\n" + "\n".join(lines)
    if len(lines) != 1:
        return ctx.failed(f"IP forwarding is set in {len(lines)} lines.", evidence)
    if SETTING.match(lines[0].split(": ", 1)[1]).group(1) != "1":
        return ctx.failed("The configured value does not enable forwarding.", evidence)
    if runtime != "1":
        return ctx.failed("IP forwarding is configured but not in effect.", evidence)
    return ctx.passed("IP forwarding is on, set in one place.", evidence)
