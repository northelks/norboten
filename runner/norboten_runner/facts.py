"""The tutor's fact bundle: python3 -m norboten_runner.facts --learner <user>

Read-only. Collects what a senior admin would glance at first — and what the learner has already
tried — so the tutor can point at the evidence that has not been looked at yet.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import pwd
import re

from norboten_runner.context import Context
from norboten_runner.report import emit, truncate

HISTORY_LINES = 60


def _history(ctx: Context) -> list[str]:
    homes = ["/root"]
    with contextlib.suppress(KeyError):
        homes.insert(0, pwd.getpwnam(ctx.learner).pw_dir)
    lines: list[str] = []
    for home in homes:
        for name in (".bash_history", ".ash_history", ".sh_history"):
            text = ctx.read(os.path.join(home, name))
            if text:
                # drop bash's "#<epoch>" timestamp lines
                lines += [line for line in text.splitlines() if not re.match(r"^#\d+$", line)]
    return lines[-HISTORY_LINES:]


def gather(ctx: Context) -> dict:
    facts: dict = {"base": ctx.facts}
    facts["uptime_seconds"] = int(float((ctx.read("/proc/uptime") or "0 0").split()[0]))
    facts["history"] = _history(ctx)
    if ctx.systemd:
        facts["failed_units"] = ctx.run(["systemctl", "--failed", "--no-legend", "--plain"]).out
        facts["system_state"] = ctx.run(["systemctl", "is-system-running"]).out.strip()
        facts["boot_errors"] = truncate(
            ctx.run(["journalctl", "-b", "-p", "err", "--no-pager", "-n", "40"]).out, 3000
        )
        facts["previous_boot_errors"] = truncate(
            ctx.run(["journalctl", "-b", "-1", "-p", "err", "--no-pager", "-n", "40"]).out, 3000
        )
    else:
        facts["services"] = ctx.run(["rc-status", "--all"]).out[-3000:]
        facts["messages_tail"] = truncate((ctx.read("/var/log/messages") or "")[-3000:], 3000)
    if ctx.facts.get("mac") == "selinux":
        facts["selinux_mode"] = ctx.run(["getenforce"]).out.strip()
        facts["avc_denials"] = truncate(
            ctx.run(["ausearch", "-m", "avc", "-ts", "recent", "-i"]).out, 3000
        )
    if ctx.facts.get("mac") == "apparmor":
        facts["apparmor_denials"] = truncate(
            ctx.run("dmesg 2>/dev/null | grep -i 'apparmor=\"DENIED\"' | tail -20").out, 3000
        )
    facts["mounts"] = ctx.run(["findmnt", "--real", "-n", "-o", "TARGET,SOURCE,FSTYPE"]).out
    facts["disk_usage"] = ctx.run(["df", "-h"]).out
    facts["listening"] = ctx.run("ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null").out[-2000:]
    return facts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--learner", required=True)
    args = ap.parse_args(argv)
    emit(gather(Context("/", phase="live", learner=args.learner)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
