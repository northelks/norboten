import os
import re


def check(ctx):
    raw = ctx.run(["systemctl", "show", "-p", "ExecStart", "--value", "inventory-api"]).out
    paths = re.findall(r"path=(\S+)", raw)
    cat = ctx.run(["systemctl", "cat", "inventory-api"]).text
    if not paths:
        return ctx.failed("inventory-api has no ExecStart at all.", cat)
    missing = [p for p in paths if not os.access(p, os.X_OK)]
    if missing:
        return ctx.failed(f"The unit starts {missing[0]}, which is not an executable.", cat)
    return ctx.passed(f"The unit starts {paths[0]}.", cat)
