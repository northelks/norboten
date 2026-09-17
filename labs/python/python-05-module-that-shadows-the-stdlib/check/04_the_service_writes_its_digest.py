import os
from importlib.machinery import SourceFileLoader


def _first(ctx):
    path = os.path.join(ctx.lab_dir, "check", "01_runs_from_its_own_directory.py")
    return SourceFileLoader("digest_first_check", path).load_module()


def check(ctx):
    first = _first(ctx)
    status = ctx.run(["systemctl", "status", "--no-pager", "-n", "8", "digest.service"]).text
    if not ctx.service_enabled("digest.service"):
        return ctx.failed("digest.service is not enabled.", status)
    restarted = ctx.run(["systemctl", "restart", "digest.service"], timeout=60)
    props = ctx.run(
        ["systemctl", "show", "digest.service", "-p", "Result", "-p", "ExecMainStatus"]
    ).out
    log = ctx.run(["journalctl", "-u", "digest.service", "-b", "-n", "12", "--no-pager"]).text
    evidence = f"restart exit {restarted.code}\n{props}\n{log}"
    if "Result=success" not in props or "ExecMainStatus=0" not in props:
        return ctx.failed("digest.service does not run to success.", evidence)
    line = (ctx.read("/var/lib/digest/today.txt") or "").strip()
    events = ctx.read("/srv/digest/events.json") or "[]"
    want = first.expected_line(events.count('"at"'))
    if line != want:
        return ctx.failed(
            "The digest the service wrote is not today's.", f"{line!r} != {want!r}\n{evidence}"
        )
    return ctx.passed("The service wrote today's digest.", f"{line}\n{evidence}")
