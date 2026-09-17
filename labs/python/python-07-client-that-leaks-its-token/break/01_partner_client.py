"""A client that logs its token, a token file anyone can read, and a service running as root."""

import os
import shutil

TOKEN = "ptk_live_7Qa4Zx91Nv3RbT0sKfLm"


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    os.makedirs("/opt/partner", exist_ok=True)
    shutil.copy(os.path.join(files, "sync.py"), "/opt/partner/sync.py")
    shutil.copy(os.path.join(files, "partner-api"), "/usr/local/bin/partner-api")
    os.chmod("/usr/local/bin/partner-api", 0o755)
    ctx.write("/etc/partner/token", TOKEN + "\n", mode=0o644)
    os.makedirs("/var/lib/partner", exist_ok=True)
    ctx.write("/var/lib/partner/orders.json", "[]\n", mode=0o644)
    for unit in ("partner-api.service", "partner-sync.service"):
        shutil.copy(os.path.join(files, unit), f"/etc/systemd/system/{unit}")
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "--now", "partner-api.service"], check=True)
    ctx.run(["systemctl", "enable", "partner-sync.service"], check=True)
    ctx.run(["systemctl", "start", "partner-sync.service"], check=True)
