"""Site content in /srv/status (default var_t context), nginx on 8090, backend on 9100."""

import os
import shutil


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    os.makedirs("/srv/status", exist_ok=True)
    ctx.write(
        "/srv/status/index.html",
        "<!doctype html><title>status</title><h1>Norboten web01 status</h1>\n",
        mode=0o644,
    )
    ctx.run(["restorecon", "-R", "/srv/status"])  # policy default for /srv is var_t — not httpd's
    shutil.copy(os.path.join(files, "status-site.conf"), "/etc/nginx/conf.d/status-site.conf")
    shutil.copy(os.path.join(files, "status-api"), "/usr/local/bin/status-api")
    os.chmod("/usr/local/bin/status-api", 0o755)
    shutil.copy(os.path.join(files, "status-api.service"), "/etc/systemd/system/status-api.service")
    ctx.run(
        [
            "restorecon",
            "-R",
            "/etc/nginx/conf.d",
            "/usr/local/bin/status-api",
            "/etc/systemd/system/status-api.service",
        ]
    )
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "--now", "status-api"], check=True)
    ctx.run(["systemctl", "enable", "nginx"], check=True)
    ctx.run(["systemctl", "restart", "nginx"])  # fails: 8090 is not an http port — as intended
