"""A retired static page, still enabled, owns port 8080."""

import os
import shutil


def apply(ctx):
    os.makedirs("/var/www/legacy-notes", exist_ok=True)
    ctx.write(
        "/var/www/legacy-notes/index.html",
        "<h1>notes</h1><p>This service was retired in 2024.</p>\n",
    )
    shutil.copy(
        os.path.join(ctx.lab_dir, "files", "notes-legacy.service"),
        "/etc/systemd/system/notes-legacy.service",
    )
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "--now", "notes-legacy"], check=True)
