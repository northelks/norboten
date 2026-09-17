"""A sed-based render that breaks on a rotated password, and leaves the result world-readable."""

import os
import shutil

PASSWORD = r"k3y/&Pa$$\1-vault"


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    for name in ("render-config", "myapp-login"):
        shutil.copy(os.path.join(files, name), f"/usr/local/bin/{name}")
        os.chmod(f"/usr/local/bin/{name}", 0o755)
    os.makedirs("/etc/myapp", exist_ok=True)
    shutil.copy(os.path.join(files, "app.conf.tmpl"), "/etc/myapp/app.conf.tmpl")
    ctx.write(
        "/etc/myapp/secrets.env", f"DB_HOST=db.internal\nDB_PASSWORD='{PASSWORD}'\n", mode=0o600
    )
    ctx.write("/var/lib/myapp-db/password", PASSWORD + "\n", mode=0o600)
    os.chmod("/var/lib/myapp-db", 0o700)
    shutil.copy(os.path.join(files, "myapp.service"), "/etc/systemd/system/myapp.service")
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "myapp.service"], check=True)
    ctx.run(["systemctl", "start", "myapp.service"])  # fails, as it has since the rotation
