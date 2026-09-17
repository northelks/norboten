"""A sync that swallows errors, has no timeout, overwrites in place, and calls the wrong port."""

import json
import os
import shutil


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    os.makedirs("/opt/sync", exist_ok=True)
    shutil.copy(os.path.join(files, "sync.py"), "/opt/sync/sync.py")
    shutil.copy(os.path.join(files, "records-api"), "/usr/local/bin/records-api")
    os.chmod("/usr/local/bin/records-api", 0o755)
    ctx.write(
        "/etc/sync/sync.env",
        "SYNC_API=http://127.0.0.1:8091/records\nSYNC_OUTPUT=/var/lib/sync/records.json\n",
        mode=0o644,
    )
    ctx.write("/var/lib/sync/records.json", json.dumps([], indent=2) + "\n", mode=0o644)
    for unit in ("records-api.service", "sync.service", "sync.timer"):
        shutil.copy(os.path.join(files, unit), f"/etc/systemd/system/{unit}")
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "--now", "records-api.service", "sync.timer"], check=True)
