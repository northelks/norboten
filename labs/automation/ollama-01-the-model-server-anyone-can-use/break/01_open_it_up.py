"""Ollama on every address with every origin allowed, nginx in front with no authentication, and the
team's password waiting to be used."""

import os
import secrets
import shutil


def lab_file(ctx, name):
    return os.path.join(ctx.lab_dir, "files", name)


def apply(ctx):
    password = ctx.state.get("password") or secrets.token_urlsafe(12)
    ctx.state["password"] = password
    ctx.save_state()
    ctx.write("/root/team-password", password + "\n", mode=0o600)

    shutil.copy(lab_file(ctx, "ollama.service"), "/etc/systemd/system/ollama.service")
    os.makedirs("/etc/systemd/system/ollama.service.d", exist_ok=True)
    shutil.copy(
        lab_file(ctx, "override.conf"), "/etc/systemd/system/ollama.service.d/override.conf"
    )
    shutil.copy(lab_file(ctx, "models.conf"), "/etc/nginx/conf.d/models.conf")
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "--now", "ollama", "nginx"], check=True)
    ctx.run(["systemctl", "restart", "ollama"], check=True)
    ctx.run(["systemctl", "reload", "nginx"], check=True)
