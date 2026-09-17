import json
import urllib.request

QUESTION = "When will my refund arrive?"


def check(ctx):
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/chat",
        data=json.dumps(
            {
                "model": "support-bot",
                "stream": False,
                "messages": [{"role": "user", "content": QUESTION}],
                "options": {"num_ctx": 8192, "num_predict": 1},
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            full = json.load(response)["prompt_eval_count"]
    except OSError as e:
        return ctx.failed("Ollama does not answer for support-bot.", str(e))
    run = ctx.run(["/opt/support-chat/ask", QUESTION], timeout=300)
    try:
        seen = json.loads(run.out.strip().splitlines()[-1])["prompt_eval_count"]
    except (ValueError, IndexError, KeyError, TypeError):
        return ctx.failed("/opt/support-chat/ask did not answer.", run.text[-600:])
    evidence = f"whole prompt: {full} tokens\nthrough the chat app: {seen} tokens\n{run.out[-300:]}"
    if seen < full:
        return ctx.failed(
            f"Through the chat app, the model evaluates {seen} of {full} prompt tokens.", evidence
        )
    return ctx.passed("Through the chat app the model evaluates the whole prompt.", evidence)
