"""Ollama tuned into the ground: a 32k context for eight parallel requests (a 3 GB key-value cache)
and a 400 MB memory cap on the service."""

import os
import shutil


def apply(ctx):
    shutil.copy(
        os.path.join(ctx.lab_dir, "files", "ollama.service"), "/etc/systemd/system/ollama.service"
    )
    os.makedirs("/etc/systemd/system/ollama.service.d", exist_ok=True)
    shutil.copy(
        os.path.join(ctx.lab_dir, "files", "tuning.conf"),
        "/etc/systemd/system/ollama.service.d/tuning.conf",
    )
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "ollama"], check=True)
    ctx.run(["systemctl", "restart", "ollama"], check=True)
