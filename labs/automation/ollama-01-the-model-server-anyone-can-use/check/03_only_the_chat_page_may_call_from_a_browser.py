import base64
import urllib.error
import urllib.request

CHAT = "https://chat.internal.example"
ELSEWHERE = "https://evil.example"


def get(url, origin, password=None):
    request = urllib.request.Request(url, headers={"Origin": origin})
    if password:
        request.add_header(
            "Authorization", "Basic " + base64.b64encode(f"team:{password}".encode()).decode()
        )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.headers.get("Access-Control-Allow-Origin")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Access-Control-Allow-Origin")
    except OSError:
        return 0, None


def check(ctx):
    password = ctx.state.get("password")
    if not password:
        return ctx.failed("The lab's password was never recorded; start the lab again.")
    foreign = get("http://127.0.0.1:11434/api/tags", ELSEWHERE)
    chat = get("http://127.0.0.1:8080/api/tags", CHAT, password)
    evidence = (
        f"Ollama, Origin {ELSEWHERE}: {foreign[0]}, Access-Control-Allow-Origin={foreign[1]}\n"
        f"proxy with the password, Origin {CHAT}: {chat[0]}, Access-Control-Allow-Origin={chat[1]}"
    )
    if foreign[0] == 0:
        return ctx.failed("Ollama does not answer on 127.0.0.1:11434.", evidence)
    if foreign[0] != 403:
        return ctx.failed(f"Ollama answers a page on {ELSEWHERE} with {foreign[0]}.", evidence)
    if chat[0] != 200:
        return ctx.failed(
            f"The chat page, through the proxy with the password, gets {chat[0]}.", evidence
        )
    return ctx.passed("Other sites are refused; the chat page gets through the proxy.", evidence)
