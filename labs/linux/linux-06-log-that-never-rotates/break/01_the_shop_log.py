"""A service user, its log directory, a 300 MB log, and a logrotate policy that is ignored (world
writable), would be skipped (a group-writable log directory without `su`), keeps nothing, and hands
the new log to root."""

import os
import shutil


def apply(ctx):
    if ctx.run(["id", "shop"]).code != 0:
        ctx.run(["useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", "shop"],
                check=True)  # fmt: skip
    os.makedirs("/var/log/shop", exist_ok=True)
    shutil.chown("/var/log/shop", "shop", "shop")
    os.chmod("/var/log/shop", 0o775)

    log = "/var/log/shop/app.log"
    with open(log, "w") as f:
        f.write("2026-09-01T00:00:01Z service started\n")
    os.truncate(log, 300 * 1024 * 1024)  # sparse: 300 MB to logrotate, nothing on disk
    shutil.chown(log, "shop", "shop")
    os.chmod(log, 0o640)

    shutil.copy(os.path.join(ctx.lab_dir, "files", "shop-log"), "/usr/local/bin/shop-log")
    os.chmod("/usr/local/bin/shop-log", 0o755)

    ctx.write(
        "/etc/logrotate.d/shop",
        "/var/log/shop/*.log {\n"
        "    size 50M\n"
        "    rotate 0\n"
        "    create 0600 root root\n"
        "    missingok\n"
        "}\n",
        mode=0o666,
    )
