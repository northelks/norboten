"""A helper module beside the program, named after a standard library module."""

import json
import os
import shutil

EVENTS = [
    {"at": "09:10", "what": "deploy 2026.9.3"},
    {"at": "11:40", "what": "disk alert cleared"},
    {"at": "16:05", "what": "new starter onboarded"},
]


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    os.makedirs("/opt/digest", exist_ok=True)
    for name in ("digest.py", "calendar.py"):
        shutil.copy(os.path.join(files, name), f"/opt/digest/{name}")
    os.makedirs("/srv/digest", exist_ok=True)
    ctx.write("/srv/digest/events.json", json.dumps(EVENTS, indent=2) + "\n")
    os.makedirs("/var/lib/digest", exist_ok=True)
    shutil.copy(os.path.join(files, "digest.service"), "/etc/systemd/system/digest.service")
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "digest.service"], check=True)
    ctx.run(["systemctl", "start", "digest.service"])  # fails, as it has since the helper arrived
