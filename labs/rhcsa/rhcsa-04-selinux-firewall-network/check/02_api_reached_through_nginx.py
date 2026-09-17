import json
import urllib.error
import urllib.request


def check(ctx):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8090/api/status", timeout=5) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return ctx.failed(
            f"/api/ through nginx returns HTTP {e.code}.",
            ctx.run("tail -5 /var/log/nginx/error.log").text,
        )
    except (OSError, ValueError) as e:
        return ctx.failed("/api/ through nginx does not answer.", str(e))
    if body.get("ok") is not True:
        return ctx.failed("/api/ answers, but not with the status service.", json.dumps(body))
    return ctx.passed("nginx reaches the status service.", json.dumps(body))
