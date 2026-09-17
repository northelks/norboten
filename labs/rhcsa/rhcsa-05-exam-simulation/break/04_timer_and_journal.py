"""A timer with a misspelled key (never fires, not enabled); the journal made volatile.

The drop-in sorts after the baseline's 90-norboten.conf (Storage=persistent), because the last file
wins — and deleting /var/log/journal alone would not survive the boot after the break, since
systemd-tmpfiles recreates it."""

import os
import shutil


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    for unit in ("sysreport.service", "sysreport.timer"):
        shutil.copy(os.path.join(files, unit), f"/etc/systemd/system/{unit}")
    ctx.write("/etc/systemd/journald.conf.d/99-retention.conf", "[Journal]\nStorage=volatile\n")
    shutil.rmtree("/var/log/journal", ignore_errors=True)
    ctx.run(["systemctl", "daemon-reload"], check=True)
