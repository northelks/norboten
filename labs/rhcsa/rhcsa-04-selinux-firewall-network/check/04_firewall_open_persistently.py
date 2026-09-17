def check(ctx):
    zone = ctx.run(["firewall-cmd", "--get-zone-of-interface=eth0"]).out.strip()
    if not zone:
        zone = ctx.run(["firewall-cmd", "--get-default-zone"]).out.strip()
    runtime = ctx.run(["firewall-cmd", f"--zone={zone}", "--query-port=8090/tcp"]).ok
    permanent = ctx.run(
        ["firewall-cmd", "--permanent", f"--zone={zone}", "--query-port=8090/tcp"]
    ).ok
    listing = ctx.run(["firewall-cmd", f"--zone={zone}", "--list-all"]).out
    if not permanent:
        return ctx.failed(
            f"Port 8090/tcp is not open in the permanent config of zone {zone}.", listing
        )
    if not runtime:
        return ctx.failed(
            f"Port 8090/tcp is configured for {zone} but not open right now.", listing
        )
    return ctx.passed(f"Port 8090/tcp is open in zone {zone}, now and after reboot.", listing)
