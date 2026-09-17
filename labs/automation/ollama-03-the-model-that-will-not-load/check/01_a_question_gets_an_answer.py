import json
import time
import urllib.error
import urllib.request


def restarts(ctx):
    out = ctx.run(["systemctl", "show", "ollama", "-p", "NRestarts", "--value"]).out.strip()
    return int(out) if out.isdigit() else -1


def wait_for_ollama():
    for _ in range(30):
        try:
            urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2).close()
            return True
        except OSError:
            time.sleep(1)
    return False


def check(ctx):
    if not ctx.service_active("ollama") or not ctx.service_enabled("ollama"):
        return ctx.failed("ollama is not running and enabled at boot.")
    if not wait_for_ollama():
        return ctx.failed("Ollama does not answer on 127.0.0.1:11434.")
    before = restarts(ctx)
    body = {
        "model": "qwen2.5:0.5b",
        "prompt": "Name one Linux command.",
        "stream": False,
        "options": {"num_predict": 8},
    }
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            status, result = response.status, json.load(response)
    except urllib.error.HTTPError as e:
        status, result = e.code, {"error": e.read().decode(errors="replace")[:400]}
    except OSError as e:
        status, result = 0, {"error": str(e)}
    time.sleep(1)
    after = restarts(ctx)
    log = ctx.run(["journalctl", "-u", "ollama", "-n", "6", "--no-pager", "-o", "cat"]).out[-800:]
    evidence = (
        f"HTTP {status}: {json.dumps(result)[:400]}\nrestarts before {before}, after {after}\n{log}"
    )
    if after != before:
        return ctx.failed("Ollama was killed and restarted while loading the model.", evidence)
    if status != 200 or not result.get("response"):
        return ctx.failed(f"The question got HTTP {status} and no answer.", evidence)
    return ctx.passed("The question got an answer, and Ollama did not restart.", evidence)
