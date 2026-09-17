"""A report that dies when grep finds nothing, and counts with uniq on unsorted input."""

import os
import shutil

QUIET_NIGHT = "".join(
    f'10.0.0.{n} - - [16/Sep/2026:02:{n:02d}:00 +0000] "GET {path} HTTP/1.1" 200 {512 + n}\n'
    for n, path in enumerate(["/", "/cart", "/products/42", "/cart", "/checkout", "/"], start=1)
)


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    shutil.copy(os.path.join(files, "errors-report"), "/usr/local/bin/errors-report")
    os.chmod("/usr/local/bin/errors-report", 0o755)
    ctx.write("/var/log/shop/access.log", QUIET_NIGHT)
    os.makedirs("/var/lib/shop", exist_ok=True)
    for unit in ("errors-report.service", "errors-report.timer"):
        shutil.copy(os.path.join(files, unit), f"/etc/systemd/system/{unit}")
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "--now", "errors-report.timer"], check=True)
