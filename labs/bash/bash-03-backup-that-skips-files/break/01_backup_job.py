"""A backup loop that splits names, loses its count in a subshell and ignores failures."""

import os
import shutil

DOCS = {
    "Contract - ACME.pdf": "%PDF-1.7 contract with ACME\n",
    "minutes/2026-09-01 board.txt": "board minutes\n",
    "minutes/  draft agenda.txt": "a name with leading blanks\n",
    "hr/-onboarding.md": "a name with a leading dash\n",
    "finance/Q3\\forecast.csv": "a name with a backslash\n",
    "notes/readme.txt": "plain\n",
}


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    shutil.copy(os.path.join(files, "backup-docs"), "/usr/local/bin/backup-docs")
    os.chmod("/usr/local/bin/backup-docs", 0o755)
    for rel, text in DOCS.items():
        ctx.write(os.path.join("/srv/docs", rel), text)
    for unit in ("backup-docs.service", "backup-docs.timer"):
        shutil.copy(os.path.join(files, unit), f"/etc/systemd/system/{unit}")
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "--now", "backup-docs.timer"], check=True)
