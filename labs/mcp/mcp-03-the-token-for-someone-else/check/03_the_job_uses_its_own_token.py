import base64
import json
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

HOME = "/home/learner"
URL = "http://127.0.0.1:8931/mcp"


def claims(token):
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}


def check(ctx):
    ctx.run(["/usr/local/bin/inventory-mcp", "restart"])
    env = ctx.read(f"{HOME}/.config/inventory/env") or ""
    token = next(
        (
            line.split("=", 1)[1].strip()
            for line in env.splitlines()
            if line.startswith("INVENTORY_TOKEN=")
        ),
        "",
    )
    aud = claims(token).get("aud")
    steps = [{"tool": "mcp__inventory__list_hosts", "input": {}}, {"text": "Done."}]
    run = claude_lab.run(
        steps, cwd=f"{HOME}/inventory-report", command=[f"{HOME}/bin/inventory-report"]
    )
    results = run.tool_results()
    said = results[0] if results else ""
    evidence = f"the job's token is for: {aud!r}\nlist_hosts: {said[:300]}\n{run.err[-300:]}"
    if aud != URL:
        return ctx.failed(f"The job's token was issued for {aud!r}, not for {URL}.", evidence)
    if ctx.state.get("host", "?") not in said:
        return ctx.failed("The job did not get the host list from the server.", evidence)
    return ctx.passed(
        "The job's own token, issued for the inventory server, lists the hosts.", evidence
    )
