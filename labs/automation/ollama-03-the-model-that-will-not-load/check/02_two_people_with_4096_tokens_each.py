import json
import re
import urllib.request


def check(ctx):
    environment = ctx.run(["systemctl", "show", "ollama", "-p", "Environment", "--value"]).out
    match = re.search(r"OLLAMA_NUM_PARALLEL=(\d+)", environment)
    parallel = int(match.group(1)) if match else 1
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/ps", timeout=10) as response:
            loaded = json.load(response).get("models", [])
    except OSError as e:
        return ctx.failed("Ollama does not answer on 127.0.0.1:11434.", str(e))
    model = next((m for m in loaded if m.get("name", "").startswith("qwen2.5:0.5b")), None)
    evidence = f"OLLAMA_NUM_PARALLEL={parallel}\nloaded: {json.dumps(loaded)[:500]}"
    if model is None:
        return ctx.failed(
            "qwen2.5:0.5b is not loaded: it has not loaded since the service started.",
            evidence,
        )
    if model.get("context_length", 0) < 4096:
        return ctx.failed(
            f"The loaded model has a {model.get('context_length')}-token context.", evidence
        )
    if parallel < 2:
        return ctx.failed(f"The server serves {parallel} request at a time.", evidence)
    return ctx.passed(
        f"The model is loaded with a {model['context_length']}-token context "
        f"for {parallel} parallel requests.",
        evidence,
    )
