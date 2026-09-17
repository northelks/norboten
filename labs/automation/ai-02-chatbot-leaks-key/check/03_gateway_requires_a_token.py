import json
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8090/ask"


def _post(token=None, timeout=20):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(URL, data=json.dumps({"prompt": "ping"}).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except OSError as e:
        return 0, str(e)


def check(ctx):
    status, body = _post()
    if status != 401:
        return ctx.failed(
            f"A request without a client token was answered with {status}.", body[:300]
        )
    status, body = _post(ctx.state["client_token"])
    if status != 200:
        return ctx.failed(
            f"A request with the client token was answered with {status}.", body[:300]
        )
    if "stub answer" not in body:
        return ctx.failed("The gateway answered, but not with the model's answer.", body[:300])
    return ctx.passed("The gateway refuses anonymous requests and serves authenticated ones.")
