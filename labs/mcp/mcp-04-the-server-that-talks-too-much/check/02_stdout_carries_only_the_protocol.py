import json


def check(ctx):
    command = "/usr/local/bin/metrics-mcp"
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "get_load"}},
    ]
    stdin = "".join(json.dumps(m) + "\n" for m in messages)
    run = ctx.run([command], input=stdin, user="learner", timeout=10)
    bad = []
    for line in run.out.splitlines():
        try:
            message = json.loads(line)
            if message.get("jsonrpc") != "2.0":
                bad.append(line)
        except ValueError:
            bad.append(line)
    evidence = f"stdout of {command}:\n{run.out[:800]}"
    if bad:
        return ctx.failed(
            f"{len(bad)} line(s) on stdout are not JSON-RPC: {bad[0][:120]!r}", evidence
        )
    if run.out.count('"jsonrpc"') < 2:
        return ctx.failed("The server did not answer on stdout.", evidence + run.err[-300:])
    return ctx.passed("Every line the server writes to stdout is a JSON-RPC message.", evidence)
