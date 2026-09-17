"""A worker whose output is block-buffered and that dies in the middle of a row."""

import os
import shutil


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    os.makedirs("/opt/ingest", exist_ok=True)
    shutil.copy(os.path.join(files, "worker.py"), "/opt/ingest/worker.py")
    os.makedirs("/srv/ingest/queue", exist_ok=True)
    for n, amount in enumerate(("120.00", "45.50", "8.75"), start=1):
        ctx.write(f"/srv/ingest/queue/invoice-{n:03d}.txt", amount + "\n")
    os.makedirs("/var/lib/ingest", exist_ok=True)
    shutil.copy(os.path.join(files, "ingest.service"), "/etc/systemd/system/ingest.service")
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "--now", "ingest.service"], check=True)
