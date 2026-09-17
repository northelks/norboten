# Functional probe: create a file as kmorris, inspect it, remove it (lab-spec §5 allows
# .norboten-probe-* files).
import os


def check(ctx):
    probe = f"/srv/project/.norboten-probe-{os.getpid()}"
    r = ctx.run(["su", "-s", "/bin/sh", "-c", f"touch {probe}", "kmorris"])
    try:
        if not r.ok:
            return ctx.failed("kmorris cannot create a file in /srv/project.", r.text)
        s = ctx.run(["stat", "-c", "%U:%G", probe]).out.strip()
        if not s.endswith(":devops"):
            return ctx.failed("A file kmorris creates there does not belong to devops.", s)
        return ctx.passed("New files in /srv/project belong to devops.", s)
    finally:
        if os.path.exists(probe):
            os.unlink(probe)
