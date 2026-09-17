"""Hostname and extra address set at runtime only."""


def apply(ctx):
    # environment, not a fault: cloud-init must not rename the host at boot, or a correct
    # hostnamectl fix would be undone by the reboot check
    ctx.write("/etc/cloud/cloud.cfg.d/99-keep-hostname.cfg", "preserve_hostname: true\n")
    ctx.run(["hostname", "web01.lab.example"], check=True)
    if "192.168.5.50/" not in ctx.run(["ip", "-4", "addr", "show", "dev", "eth0"]).out:
        ctx.run(["ip", "addr", "add", "192.168.5.50/24", "dev", "eth0"], check=True)
