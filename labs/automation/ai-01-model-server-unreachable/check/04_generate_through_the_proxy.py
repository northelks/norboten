import json
import urllib.error
import urllib.request

PROMPT = {
    "model": "qwen2.5:0.5b",
    "prompt": "Reply with the single word: ready",
    "stream": False,
    "options": {"num_predict": 12, "temperature": 0},
}


def check(ctx):
    req = urllib.request.Request(
        "http://127.0.0.1:8080/api/generate",
        data=json.dumps(PROMPT).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return ctx.failed(
            f"Generation through the proxy returns HTTP {e.code}.",
            ctx.run("tail -5 /var/log/nginx/error.log").text,
        )
    except (OSError, ValueError) as e:
        return ctx.failed("Generation through the proxy failed.", str(e))
    text = (body.get("response") or "").strip()
    if not text:
        return ctx.failed("The model server answered with no text.", json.dumps(body)[:400])
    return ctx.passed("The model answers through the proxy.", text[:200])
