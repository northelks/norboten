import glob
import os


def check(ctx):
    confs = [
        "/etc/systemd/journald.conf",
        *sorted(glob.glob("/etc/systemd/journald.conf.d/*.conf")),
    ]
    storage = "auto"
    for c in confs:
        for line in (ctx.read(c) or "").splitlines():
            if line.strip().startswith("Storage="):
                storage = line.split("=", 1)[1].strip()
    if storage == "volatile" or storage == "none":
        return ctx.failed(f"journald is configured with Storage={storage}.")
    if not os.path.isdir("/var/log/journal"):
        return ctx.failed("There is no /var/log/journal, so the journal is not kept.")
    boots = ctx.run(["journalctl", "--list-boots", "--no-pager"]).out
    if ctx.phase == "post_reboot" and len(boots.strip().splitlines()) < 2:
        return ctx.failed("The journal from the previous boot was not kept.", boots)
    return ctx.passed("The journal is kept across reboots.", boots)
