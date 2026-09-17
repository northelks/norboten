import json
import os
import time
import urllib.request

MODEL = "http://127.0.0.1:11500"
INBOX = "/var/lib/inbox-agent/inbox"
DONE = "/var/lib/inbox-agent/done"
PROBE_MESSAGE = ".norboten-probe-loop.txt"
LIMIT = 10


def post(path, payload):
    request = urllib.request.Request(
        MODEL + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def requests_seen():
    with urllib.request.urlopen(MODEL + "/_requests", timeout=10) as response:
        return json.load(response)


def check(ctx):
    if ctx.run(["systemctl", "is-active", "--quiet", "norboten-model.service"]).code != 0:
        return ctx.failed("The lab's model endpoint, norboten-model.service, is not running.")
    post("/_script", [{"tool": "read_message", "arguments": {"id": PROBE_MESSAGE}}])
    ctx.write(os.path.join(INBOX, PROBE_MESSAGE), "From: probe@example.org\n\nHm?\n", mode=0o644)
    ctx.run(["systemctl", "reset-failed", "inbox-agent.service"])
    try:
        ctx.run(["systemctl", "start", "inbox-agent.service"], timeout=30)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and os.path.exists(os.path.join(INBOX, PROBE_MESSAGE)):
            time.sleep(0.5)
        still_there = os.path.exists(os.path.join(INBOX, PROBE_MESSAGE))
        seen = requests_seen()
    finally:
        if os.path.exists(os.path.join(INBOX, PROBE_MESSAGE)):
            ctx.run(["systemctl", "kill", "inbox-agent.service"])
        for directory in (INBOX, DONE):
            path = os.path.join(directory, PROBE_MESSAGE)
            if os.path.exists(path):
                os.remove(path)
        post("/_script", [{"text": "Thank you for your message."}])
    log = ctx.run(["journalctl", "-u", "inbox-agent", "-n", "5", "--no-pager", "-o", "cat"]).out
    evidence = f"model calls for the message: {len(seen)}\n{log}"
    if not seen:
        return ctx.failed("The agent never called the model for the grader's message.", evidence)
    if still_there or len(seen) > LIMIT:
        return ctx.failed(
            f"A model that never stops calling tools got {len(seen)} calls "
            f"{'and was still going after 30 s' if still_there else 'for one message'}.",
            evidence,
        )
    return ctx.passed(f"The agent gave up on the message after {len(seen)} model calls.", evidence)
