"""Install ledger as an enabled service, with no logrotate config."""

import os
import shutil


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    shutil.copy(os.path.join(files, "ledger"), "/usr/local/bin/ledger")
    os.chmod("/usr/local/bin/ledger", 0o755)
    if ctx.systemd:
        shutil.copy(os.path.join(files, "ledger.service"), "/etc/systemd/system/ledger.service")
        ctx.run(["systemctl", "daemon-reload"], check=True)
        ctx.run(["systemctl", "enable", "ledger"], check=True)
    else:
        shutil.copy(os.path.join(files, "ledger.openrc"), "/etc/init.d/ledger")
        os.chmod("/etc/init.d/ledger", 0o755)
        ctx.run(["rc-update", "add", "ledger", "default"], check=True)
