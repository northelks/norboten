import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

URL = "http://127.0.0.1:8090/ask"


def check(ctx):
    token = ctx.state["client_token"]

    def one(_):
        req = urllib.request.Request(
            URL,
            data=json.dumps({"prompt": "ping"}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code
        except OSError:
            return 0

    with ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(one, range(40)))
    counts = {c: codes.count(c) for c in sorted(set(codes))}
    if counts.get(429, 0) == 0:
        return ctx.failed("A burst of 40 requests was never rate-limited.", json.dumps(counts))
    if counts.get(200, 0) == 0:
        return ctx.failed(
            "The rate limit rejects everything, even the first request.", json.dumps(counts)
        )
    return ctx.passed(
        "Bursts are rejected with 429 while normal use goes through.", json.dumps(counts)
    )
