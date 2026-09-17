"""A service that holds a large deleted spool file on the volume."""

import os
import shutil


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    shutil.copy(os.path.join(files, "app-spooler"), "/usr/local/bin/app-spooler")
    os.chmod("/usr/local/bin/app-spooler", 0o755)
    shutil.copy(
        os.path.join(files, "app-spooler.service"), "/etc/systemd/system/app-spooler.service"
    )
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "--now", "app-spooler"], check=True)
    ctx.run("sleep 2")
