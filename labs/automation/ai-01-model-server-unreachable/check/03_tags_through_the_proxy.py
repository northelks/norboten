import json
import urllib.error
import urllib.request


def check(ctx):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/api/tags", timeout=10) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return ctx.failed(
            f"The proxy answers /api/tags with HTTP {e.code}.",
            ctx.run("tail -5 /var/log/nginx/error.log").text,
        )
    except (OSError, ValueError) as e:
        return ctx.failed("Nothing usable answers on port 8080.", str(e))
    names = [m.get("name", "") for m in body.get("models", [])]
    if not any(n.startswith("qwen2.5:0.5b") for n in names):
        return ctx.failed("The proxy answers, but the model is not listed.", json.dumps(names))
    return ctx.passed("The model is listed through the proxy.", json.dumps(names))
