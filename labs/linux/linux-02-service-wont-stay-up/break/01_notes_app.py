"""notes user, data in /srv/notes, app installed; config readable by root only."""

import os
import shutil


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    if not ctx.run(["id", "notes"]).ok:
        ctx.run(
            ["useradd", "--system", "--no-create-home", "-s", "/usr/sbin/nologin", "notes"],
            check=True,
        )
    os.makedirs("/srv/notes", exist_ok=True)
    ctx.write(
        "/srv/notes/welcome.txt",
        "Welcome to notes. If you can read this, it works.\n",
        mode=0o640,
        owner="notes",
        group="notes",
    )
    ctx.write(
        "/srv/notes/oncall.txt",
        "On call this week: apatel.\n",
        mode=0o640,
        owner="notes",
        group="notes",
    )
    ctx.run(["chown", "notes:notes", "/srv/notes"], check=True)
    os.chmod("/srv/notes", 0o750)
    shutil.copy(os.path.join(files, "notes-app"), "/usr/local/bin/notes-app")
    os.chmod("/usr/local/bin/notes-app", 0o755)
    ctx.write("/etc/notes/notes.ini", "[notes]\nport = 8080\ndata = /srv/notes\n", mode=0o600)
    shutil.copy(os.path.join(files, "notes.service"), "/etc/systemd/system/notes.service")
    ctx.run(["systemctl", "daemon-reload"], check=True)
