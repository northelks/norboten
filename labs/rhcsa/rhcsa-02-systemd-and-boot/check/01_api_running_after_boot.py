import json
import urllib.request


def check(ctx):
    status = ctx.run(["systemctl", "status", "--no-pager", "-n", "8", "inventory-api"]).text
    if not ctx.service_enabled("inventory-api"):
        return ctx.failed("inventory-api is not set to start at boot.", status)
    if not ctx.service_active("inventory-api"):
        return ctx.failed("inventory-api is not running.", status)
    try:
        with urllib.request.urlopen("http://127.0.0.1:8081/health", timeout=5) as r:
            body = json.loads(r.read())
    except (OSError, ValueError) as e:
        return ctx.failed("inventory-api is running but /health does not answer.", str(e))
    if body.get("status") != "ok":
        return ctx.failed("/health answers, but not with status ok.", json.dumps(body))
    return ctx.passed("inventory-api is running, enabled, and healthy.", json.dumps(body))
