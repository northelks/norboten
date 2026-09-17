import os
import time


def check(ctx):
    if not ctx.service_enabled("ledger"):
        return ctx.failed("ledger is not set to start at boot.")
    if not ctx.service_active("ledger"):
        return ctx.failed("ledger is not running.")
    log = "/var/log/app/ledger.log"
    try:
        age = time.time() - os.stat(log).st_mtime
    except OSError:
        age = None
    if age is None or age > 15:
        # it may be writing to a deleted file — which is exactly the problem, not a pass
        return ctx.failed("ledger is running but its log file is not being written.")
    return ctx.passed("ledger is running, enabled at boot, and writing its log.")
