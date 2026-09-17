"""API and config-sync installed; the API only orders itself After= config-sync, never Wants= it."""

import os
import shutil


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    for name in ("inventory-api", "config-sync"):
        shutil.copy(os.path.join(files, name), f"/usr/local/bin/{name}")
        os.chmod(f"/usr/local/bin/{name}", 0o755)
        shutil.copy(
            os.path.join(files, f"{name}.service"), f"/usr/lib/systemd/system/{name}.service"
        )
    ctx.write("/etc/inventory/source.json", '{"items": ["web01", "db01", "cache01"]}\n')
    ctx.run(["systemctl", "daemon-reload"], check=True)
    # prepared by hand once, so a manual start works — until /run is wiped by a reboot
    ctx.run(["/usr/local/bin/config-sync"], check=True)
