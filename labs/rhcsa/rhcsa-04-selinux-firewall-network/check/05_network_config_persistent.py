def check(ctx):
    static = ctx.run(["hostnamectl", "hostname", "--static"]).out.strip()
    if not static:
        static = (ctx.read("/etc/hostname") or "").strip()
    if static != "web01.lab.example":
        return ctx.failed(f"The configured hostname is {static or 'unset'}.", static)
    con = ctx.run(["nmcli", "-g", "GENERAL.CONNECTION", "device", "show", "eth0"]).out.strip()
    addrs = ctx.run(["nmcli", "-g", "ipv4.addresses", "connection", "show", con]).out
    live = ctx.run(["ip", "-4", "addr", "show", "dev", "eth0"]).out
    if "192.168.5.50/24" not in addrs:
        return ctx.failed(
            f"The connection profile {con!r} does not include 192.168.5.50/24.",
            f"ipv4.addresses: {addrs.strip()}",
        )
    if "192.168.5.50/24" not in live:
        return ctx.failed("192.168.5.50/24 is configured but not assigned.", live)
    return ctx.passed("Hostname and address are configured persistently.", f"{static}\n{addrs}")
