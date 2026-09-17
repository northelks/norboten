import json
import os
import shutil
import tempfile


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        out = os.path.join(base, "orders.json")
        os.chmod(base, 0o777)
        r = ctx.run(["systemctl", "restart", "partner-sync.service"], timeout=60)
        props = ctx.run(
            ["systemctl", "show", "partner-sync.service", "-p", "Result", "-p", "ExecMainStatus"]
        ).out
        live = ctx.read("/var/lib/partner/orders.json") or ""
        hand = ctx.run(["python3", "/opt/partner/sync.py"], env={"PARTNER_OUT": out}, timeout=30)
        by_hand = ctx.read(out) or ""
        evidence = (
            f"restart exit {r.code}\n{props}\nservice orders: {live!r}\n"
            f"by hand exit {hand.code}\n{hand.text}\nby-hand orders: {by_hand!r}"
        )
        if "Result=success" not in props or "ExecMainStatus=0" not in props:
            return ctx.failed("partner-sync.service does not run to success.", evidence)
        for text, who in ((live, "the service"), (by_hand, "a run by hand")):
            try:
                orders = json.loads(text)
            except ValueError:
                return ctx.failed(f"The orders {who} wrote are not valid JSON.", evidence)
            if sorted(o.get("id") for o in orders) != ["P-1001", "P-1002"]:
                return ctx.failed(f"The orders {who} wrote are not the partner's.", evidence)
        return ctx.passed(
            "The sync fetches the partner's orders, by hand and as a service.", evidence
        )
    finally:
        shutil.rmtree(base, ignore_errors=True)
