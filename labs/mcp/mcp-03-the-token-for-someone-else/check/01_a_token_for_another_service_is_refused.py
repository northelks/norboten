import json
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
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except OSError as e:
        return 0, str(e)


def check(ctx):
    ctx.run(["/usr/local/bin/inventory-mcp", "restart"])  # grade the settings it would start with
    minted = {}
    for label, audience in (("own", URL), ("billing", "https://billing.example/api")):
        minted[label] = ctx.run(["/usr/local/bin/lab-idp", "mint", "--audience", audience]).out
    own, _ = ask(minted["own"].strip())
    other, other_body = ask(minted["billing"].strip())
    evidence = (
        f"token for {URL}: HTTP {own}\ntoken for the billing API: HTTP {other} {other_body[:200]}"
    )
    if own != 200:
        return ctx.failed(f"The server refuses even a token issued for it (HTTP {own}).", evidence)
    if other != 401:
        return ctx.failed(
            "The server accepted a token issued for the billing API: it never checks the audience.",
            evidence,
        )
    return ctx.passed("A token issued for another service is refused with 401.", evidence)
