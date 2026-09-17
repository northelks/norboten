"""nginx in front of the model server — pointed at the wrong port, buffering, short timeout."""

import os
import shutil


def apply(ctx):
    shutil.copy(
        os.path.join(ctx.lab_dir, "files", "model-proxy.conf"), "/etc/nginx/conf.d/model-proxy.conf"
    )
    ctx.run(["systemctl", "enable", "--now", "nginx"], check=True)
    ctx.run(["systemctl", "reload", "nginx"])
