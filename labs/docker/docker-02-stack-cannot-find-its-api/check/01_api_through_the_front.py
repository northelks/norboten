import json
import time
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8088/api/status.json"


def check(ctx):
    body, error = "", ""
    for _ in range(10):  # after a boot, the containers may still be starting
        try:
            with urllib.request.urlopen(URL, timeout=3) as r:
                body = r.read().decode(errors="replace")
            break
        except urllib.error.HTTPError as e:
            error = f"HTTP {e.code}"
            break
        except OSError as e:
            error = str(e)
            time.sleep(2)
    ps = ctx.run("cd /srv/shop && docker compose ps --all", timeout=20).text
    evidence = f"GET {URL} -> {body.strip() or error}\n\n{ps}"
    try:
        doc = json.loads(body)
    except ValueError:
        return ctx.failed("The front does not return the API's status document.", evidence)
    if doc.get("service") != "api" or doc.get("status") != "ok":
        return ctx.failed("The front returns something other than the API's status.", evidence)
    return ctx.passed("The API answers through the front.", evidence)
