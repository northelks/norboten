import os
import re

CRON_PATH = "/usr/bin:/bin"  # what cron gives a job when the crontab sets no PATH


def _entries(text, has_user):
    path, lines = None, []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"^PATH\s*=\s*(.+)$", s)
        if m:
            path = m.group(1).strip().strip('"')
            continue
        fields = s.split(None, 6 if has_user else 5)
        cmd = fields[-1] if len(fields) >= (7 if has_user else 6) else ""
        if "backup-data" in cmd:
            lines.append((line, cmd))
    return path, lines


def check(ctx):
    if ctx.systemd:
        conf, has_user, daemon = "/etc/cron.d/backup-data", True, "cron"
    else:
        conf, has_user, daemon = "/etc/crontabs/root", False, "crond"
    text = ctx.read(conf) or ""
    path, entries = _entries(text, has_user)
    if not entries:
        return ctx.failed(f"No job in {conf} runs the backup.", text)
    line, cmd = entries[0]
    program = cmd.split()[0]
    search = (path or CRON_PATH).split(":")
    resolved = (
        program
        if program.startswith("/")
        else next(
            (
                os.path.join(d, program)
                for d in search
                if os.access(os.path.join(d, program), os.X_OK)
            ),
            None,
        )
    )
    if not resolved or not os.access(resolved, os.X_OK):
        return ctx.failed(f"cron would not find {program!r} with PATH={path or CRON_PATH}.", line)
    if not ctx.service_enabled(daemon) or not ctx.service_active(daemon):
        return ctx.failed(f"{daemon} is not running and enabled.")
    return ctx.passed(f"cron can run the backup ({resolved}).", line)
