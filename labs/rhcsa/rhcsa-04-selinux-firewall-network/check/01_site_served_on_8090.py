import urllib.error
import urllib.request


def check(ctx):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8090/", timeout=5) as r:
            body = r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return ctx.failed(
            f"nginx answers on 8090 with HTTP {e.code}.",
            ctx.run("tail -5 /var/log/nginx/error.log").text,
        )
    except OSError as e:
        status = ctx.run(["systemctl", "status", "--no-pager", "-n", "5", "nginx"]).text
        return ctx.failed("Nothing answers on port 8090.", f"{e}\n{status}")
    if "Norboten web01 status" not in body:
        return ctx.failed("Port 8090 answers, but not with the page from /srv/status.", body[:300])
    return ctx.passed("The site is served on port 8090.")
