"""A huge log held open by ledger, then deleted; plus a stale archive. df and du disagree."""

import os


def _svc(ctx, action):
    if ctx.systemd:
        return ctx.run(["systemctl", action, "ledger"])
    return ctx.run(["rc-service", "ledger", action])


def apply(ctx):
    log = "/var/log/app/ledger.log"
    _svc(ctx, "stop")
    if os.path.exists(log):
        os.unlink(log)
    # fallocate reserves blocks without writing them: the guest disk fills, the host image doesn't.
    ctx.run(["fallocate", "-l", "700M", log], check=True)
    if not _svc(ctx, "start").ok:
        raise RuntimeError("ledger did not start")
    os.makedirs("/var/log/app/archive", exist_ok=True)
    for year in ("2023", "2024"):
        ctx.run(["fallocate", "-l", "90M", f"/var/log/app/archive/ledger-{year}.log"], check=True)
    ctx.run("sleep 2")
    os.unlink(log)  # "the colleague deleted the biggest file"
