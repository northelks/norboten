import json
import time
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8931/mcp"


def ask(token):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).encode()
    request = urllib.request.Request(
        URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except OSError:
        return 0


def check(ctx):
    ctx.run(["/usr/local/bin/inventory-mcp", "restart"])
    mint = ["/usr/local/bin/lab-idp", "mint", "--audience", URL, "--ttl", "3600"]
    fresh = ctx.run(mint).out.strip()
    old = ctx.run([*mint, "--issued-at", str(time.time() - 7200)]).out.strip()
    fresh_status, old_status = ask(fresh), ask(old)
    evidence = (
        f"a fresh token: HTTP {fresh_status}\na token that expired an hour ago: HTTP {old_status}"
    )
    if fresh_status != 200:
        return ctx.failed(
            f"The server refuses a fresh token issued for it (HTTP {fresh_status}).", evidence
        )
    if old_status != 401:
        return ctx.failed("The server accepted a token that expired an hour ago.", evidence)
    return ctx.passed("An expired token is refused; a fresh one is accepted.", evidence)
