"""A report that opens every file with the machine's encoding, and a cp1252 export."""

import os
import shutil

UTF8 = "name,city\nAnna Kowalska,Kraków\nJonas Müller,München\n"
CP1252 = "name,city\nRuiz Peña,Málaga\nAnaïs Fabre,Nîmes\n"
README = """Exports in this directory
-------------------------
*.cp1252.csv  the old Windows tool (code page 1252)
*.csv         everything else: UTF-8
"""


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    os.makedirs("/opt/members", exist_ok=True)
    shutil.copy(os.path.join(files, "report.py"), "/opt/members/report.py")
    os.makedirs("/srv/members", exist_ok=True)
    with open("/srv/members/new-2026-09.csv", "w", encoding="utf-8") as f:
        f.write(UTF8)
    with open("/srv/members/legacy-2026-09.cp1252.csv", "w", encoding="cp1252") as f:
        f.write(CP1252)
    ctx.write("/srv/members/README", README)
    os.makedirs("/var/lib/members", exist_ok=True)
    for unit in ("members-report.service", "members-report.timer"):
        shutil.copy(os.path.join(files, unit), f"/etc/systemd/system/{unit}")
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "--now", "members-report.timer"], check=True)
