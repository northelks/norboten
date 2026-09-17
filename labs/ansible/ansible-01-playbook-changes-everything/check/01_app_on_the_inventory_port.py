import time
import urllib.request


def check(ctx):
    listening = ctx.run(["ss", "-Hltnp"]).out
    if not ctx.service_enabled("app"):
        return ctx.failed("The app service does not start at boot.", listening)
    body, error = "", ""
    for _ in range(10):  # just after a boot the service may still be starting
        try:
            with urllib.request.urlopen("http://127.0.0.1:8081/", timeout=3) as r:
                body = r.read().decode(errors="replace")
            break
        except OSError as e:
            error = str(e)
            time.sleep(1)
    evidence = f"GET http://127.0.0.1:8081/ -> {body.strip() or error}\n{listening}"
    if "inventory service" not in body:
        return ctx.failed("Nothing answers as the application on port 8081.", evidence)
    return ctx.passed("The application answers on 8081.", evidence)
