"""The tidy-up: models moved to /srv/models and left owned by root, service never enabled."""

import os
import shutil


def apply(ctx):
    if not os.path.isdir("/srv/models") and os.path.isdir("/var/lib/ollama/models"):
        shutil.move("/var/lib/ollama/models", "/srv/models")
    ctx.run(["chown", "-R", "root:root", "/srv/models"], check=True)
    os.chmod("/srv/models", 0o700)
    shutil.copy(
        os.path.join(ctx.lab_dir, "files", "ollama.service"), "/etc/systemd/system/ollama.service"
    )
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "disable", "--now", "ollama"])
