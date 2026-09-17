import base64
import urllib.error
import urllib.request

URL = "http://127.0.0.1:8080/api/tags"


def status(user=None, password=None):
    request = urllib.request.Request(URL)
    if user is not None:
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        request.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except OSError as e:
        return 0, str(e)


def check(ctx):
    password = ctx.state.get("password")
    if not password:
        return ctx.failed("The lab's password was never recorded; start the lab again.")
    anonymous, _ = status()
    wrong, _ = status("team", password + "x")
    right, body = status("team", password)
    evidence = (
        f"no credentials: {anonymous}\nwrong password: {wrong}\n"
        f"team + password: {right}\n{body[:300]}"
    )
    if anonymous != 401:
        return ctx.failed(f"A request without credentials gets {anonymous}, not 401.", evidence)
    if wrong != 401:
        return ctx.failed(f"A wrong password gets {wrong}, not 401.", evidence)
    if right != 200 or "qwen2.5:0.5b" not in body:
        return ctx.failed(
            f"team with the right password gets {right}, without the model list.", evidence
        )
    return ctx.passed(
        "The proxy refuses strangers with 401 and lists the models for the team.", evidence
    )
