"""Two services on separate networks, a proxy to its own localhost, a published API, no restart."""

import os
import shutil


def apply(ctx):
    if not os.path.exists("/srv/shop/compose.yaml"):
        shutil.copytree(os.path.join(ctx.lab_dir, "files", "shop"), "/srv/shop")
    ctx.run(["systemctl", "enable", "--now", "docker.service"], check=True, timeout=90)
    ctx.run("cd /srv/shop && docker compose up -d", check=True, timeout=90)
