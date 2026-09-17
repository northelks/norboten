import json
import urllib.request


def parameters(text):
    found = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            found[parts[0]] = parts[-1].strip('"')
    return found


def check(ctx):
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/show",
        data=json.dumps({"model": "support-bot"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            shown = json.load(response)
    except OSError as e:
        return ctx.failed("Ollama does not know a model called support-bot.", str(e))
    params = parameters(shown.get("parameters"))
    evidence = shown.get("parameters", "")
    if "temperature" not in params:
        return ctx.failed(
            "support-bot sets no temperature, so it samples at the base model's default.", evidence
        )
    if float(params["temperature"]) > 0.3:
        return ctx.failed(f"support-bot samples at temperature {params['temperature']}.", evidence)
    return ctx.passed(f"support-bot samples at temperature {params['temperature']}.", evidence)
