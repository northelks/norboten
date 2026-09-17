import os
import shutil
import tempfile

BAD_TOKEN = "ptk_live_0000000000000000000000"


def check(ctx):
    token = (ctx.read("/etc/partner/token") or "").strip()
    if not token:
        return ctx.failed("The token file is gone: the sync has nothing to authenticate with.")
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        os.chmod(base, 0o777)
        out = os.path.join(base, "orders.json")
        wrong = os.path.join(base, "wrong-token")
        ctx.write(wrong, BAD_TOKEN + "\n", mode=0o644)
        ctx.run(["systemctl", "restart", "partner-sync.service"], timeout=60)
        # this run's own journal: the earlier, broken runs are in the same second of the same boot
        invocation = ctx.run(
            ["systemctl", "show", "partner-sync.service", "-p", "InvocationID", "--value"]
        ).out.strip()
        journal = ctx.run(
            ["journalctl", f"_SYSTEMD_INVOCATION_ID={invocation}", "-n", "60", "--no-pager"]
        ).text
        debug = ctx.run(
            ["python3", "/opt/partner/sync.py"],
            env={"PARTNER_OUT": out, "PARTNER_LOG_LEVEL": "DEBUG"},
            timeout=30,
        )
        failing = ctx.run(
            ["python3", "/opt/partner/sync.py"],
            env={"PARTNER_OUT": out, "PARTNER_TOKEN_FILE": wrong, "PARTNER_LOG_LEVEL": "DEBUG"},
            timeout=30,
        )
        evidence = (
            f"invocation {invocation}\njournal:\n{journal[-1200:]}\n\n"
            f"DEBUG run:\n{debug.text[-1200:]}\n\nfailing run:\n{failing.text[-1200:]}"
        )
        where = []
        if token in journal:
            where.append("the journal")
        if token in debug.text:
            where.append("a DEBUG run")
        if BAD_TOKEN in failing.text:
            where.append("the error of a failing run")
        if where:
            return ctx.failed(f"The token is printed in {', '.join(where)}.", evidence)
        if failing.code == 0:
            return ctx.failed("A wrong token is reported as a successful sync.", evidence)
        return ctx.passed("No run prints the token, and a wrong one still fails.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
