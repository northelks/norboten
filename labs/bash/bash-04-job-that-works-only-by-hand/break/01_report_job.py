"""A report that needs a login shell's PATH and /opt/reports as its working directory."""

import os
import shutil

PROFILE = """
# reporting tools (added by ops, 2025)
export PATH="$PATH:/opt/reports/tools/bin"
cd /opt/reports 2>/dev/null
"""


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    for name, target in (
        ("nightly-report", "/opt/reports/bin/nightly-report"),
        ("report-fmt", "/opt/reports/tools/bin/report-fmt"),
    ):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy(os.path.join(files, name), target)
        os.chmod(target, 0o755)
    ctx.write("/opt/reports/report.conf", 'projects="/srv/projects/alpha /srv/projects/beta"\n')
    for project, size in (("alpha", 300_000), ("beta", 120_000)):
        ctx.write(f"/srv/projects/{project}/data.bin", "x" * size)
    os.makedirs("/var/lib/reports", exist_ok=True)
    profile = ctx.read("/root/.bashrc") or ""
    if "/opt/reports/tools/bin" not in profile:
        ctx.write("/root/.bashrc", profile + PROFILE)
    for unit in ("nightly-report.service", "nightly-report.timer"):
        shutil.copy(os.path.join(files, unit), f"/etc/systemd/system/{unit}")
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "--now", "nightly-report.timer"], check=True)
