import os
import re

LIMIT = 50 * 1024 * 1024


def check(ctx):
    app = "/var/log/shop/app.log"
    siblings = sorted(
        f for f in os.listdir("/var/log/shop") if re.fullmatch(r"app\.log\.\d+(\.gz)?", f)
    )
    size = os.stat(app).st_size if os.path.exists(app) else 0
    evidence = f"app.log: {size} bytes\nrotated: {', '.join(siblings) or 'none'}"
    if size >= LIMIT:
        return ctx.failed(f"app.log is still {size // (1024 * 1024)} MB.", evidence)
    if not siblings:
        return ctx.failed(
            "app.log is small, but its history is gone: nothing was rotated.", evidence
        )
    return ctx.passed("The big log was rotated; its history is kept beside it.", evidence)
