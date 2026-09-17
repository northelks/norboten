"""The lying backup script, real data with awkward names, and a cron entry without a PATH."""

import os
import shutil


def apply(ctx):
    shutil.copy(os.path.join(ctx.lab_dir, "files", "backup-data"), "/usr/local/bin/backup-data")
    os.chmod("/usr/local/bin/backup-data", 0o755)
    os.makedirs("/var/backups", exist_ok=True)
    for name, text in {
        "invoices/2026 Q3 summary.csv": "id,total\n1,100\n",
        "invoices/march.csv": "id,total\n2,200\n",
        "contracts/Acme Corp — signed.pdf": "%PDF-1.4 stand-in\n",
        "notes.txt": "keep me\n",
    }.items():
        ctx.write(os.path.join("/srv/data", name), text)
    if ctx.systemd:
        ctx.write(
            "/etc/cron.d/backup-data", "# nightly backup\n15 2 * * * root backup-data\n", mode=0o644
        )
        ctx.run(["systemctl", "enable", "--now", "cron"], check=True)
    else:
        crontab = ctx.read("/etc/crontabs/root") or ""
        if "backup-data" not in crontab:
            ctx.write("/etc/crontabs/root", crontab.rstrip("\n") + "\n15 2 * * * backup-data\n")
        ctx.run(["rc-update", "add", "crond", "default"])
        ctx.run(["rc-service", "crond", "start"])
