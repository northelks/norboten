import urllib.error
import urllib.request


def check(ctx):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/", timeout=5) as r:
            status, headers, body = r.status, r.headers, r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        status, headers, body = e.code, e.headers, e.read().decode(errors="replace")
    except OSError as e:
        return ctx.failed("Nothing answers on port 8080.", str(e))
    if headers.get("X-Notes-Service") != "1":
        return ctx.failed("Port 8080 answers, but it is not the notes service.", body[:500])
    if status != 200 or "Welcome to notes" not in body:
        return ctx.failed("notes answers but cannot show its notes.", body[:1000])
    return ctx.passed("Port 8080 serves the notes.", body[:500])
