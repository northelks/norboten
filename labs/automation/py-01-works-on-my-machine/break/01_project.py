"""The ETL project, its venv, a world-readable token, and units that run it the wrong way."""

import os
import secrets
import shutil


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    if not ctx.run(["id", "etl"]).ok:
        ctx.run(
            [
                "useradd",
                "--system",
                "--home-dir",
                "/opt/etl",
                "--shell",
                "/usr/sbin/nologin",
                "etl",
            ],
            check=True,
        )
    os.makedirs("/opt/etl/config", exist_ok=True)
    shutil.copy(os.path.join(files, "report.py"), "/opt/etl/report.py")
    ctx.write(
        "/opt/etl/config/settings.json",
        '{"api": "http://127.0.0.1:8900", "output": "/var/lib/etl/reports/latest.json"}\n',
    )
    if not os.path.exists("/opt/etl/.venv/bin/python"):
        ctx.run(["python3", "-m", "venv", "/opt/etl/.venv"], check=True)
        ctx.run(
            [
                "/opt/etl/.venv/bin/pip",
                "install",
                "-q",
                "--no-index",
                "--find-links",
                "/opt/wheels",
                "httpx",
            ],
            check=True,
            timeout=110,
        )
    os.makedirs("/var/lib/etl/reports", exist_ok=True)  # root-owned: etl cannot write yet
    ctx.write("/etc/etl/token", secrets.token_hex(16) + "\n", mode=0o644)
    shutil.copy(os.path.join(files, "metrics-api"), "/usr/local/bin/metrics-api")
    os.chmod("/usr/local/bin/metrics-api", 0o755)
    for unit in ("metrics-api.service", "etl-report.service", "etl-report.timer"):
        shutil.copy(os.path.join(files, unit), f"/etc/systemd/system/{unit}")
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "--now", "metrics-api"], check=True)
