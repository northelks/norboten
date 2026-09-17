import json
import urllib.request

OLLAMA = "http://127.0.0.1:11434"
QUESTION = "When will my refund arrive?"


def post(path, body, timeout=300):
    request = urllib.request.Request(
        OLLAMA + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def check(ctx):
    revision = ctx.state.get("revision")
    try:
        shown = post("/api/show", {"model": "support-bot"}, timeout=30)
    except OSError as e:
        return ctx.failed("Ollama does not know a model called support-bot.", str(e))
    if f"policy revision {revision}" not in (shown.get("system") or ""):
        return ctx.failed(
            "support-bot's system prompt is not the team's rules.",
            (shown.get("system") or "")[:300],
        )
    # the whole prompt, with a context far larger than it needs, is the yardstick
    full = post(
        "/api/chat",
        {
            "model": "support-bot",
            "stream": False,
            "messages": [{"role": "user", "content": QUESTION}],
            "options": {"num_ctx": 8192, "num_predict": 1},
        },
    )["prompt_eval_count"]
    default = post(
        "/api/chat",
        {
            "model": "support-bot",
            "stream": False,
            "messages": [{"role": "user", "content": QUESTION}],
            "options": {"num_predict": 1},
        },
    )["prompt_eval_count"]
    evidence = (
        f"prompt tokens with the rules and the question: {full}\n"
        f"prompt tokens support-bot evaluates with its own settings: {default}\n"
        f"parameters:\n{shown.get('parameters', '')}"
    )
    if default < full:
        return ctx.failed(
            f"support-bot evaluates {default} of the {full} prompt tokens: "
            "most of its rules are cut off.",
            evidence,
        )
    return ctx.passed(f"support-bot evaluates all {full} prompt tokens, rules included.", evidence)
