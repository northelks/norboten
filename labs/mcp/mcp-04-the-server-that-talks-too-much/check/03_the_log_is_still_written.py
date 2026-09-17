import json

LOG_FILE = "/var/log/metrics-mcp.log"


def check(ctx):
    before = len(ctx.read(LOG_FILE) or "")
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "get_load"}},
    ]
    stdin = "".join(json.dumps(m) + "\n" for m in messages)
    run = ctx.run(["/usr/local/bin/metrics-mcp"], input=stdin, user="learner", timeout=10)
    written = (ctx.read(LOG_FILE) or "")[before:]
    elsewhere = run.err + written
    evidence = f"stderr:\n{run.err[-400:]}\n{LOG_FILE}, new lines:\n{written[-400:]}"
    if "get_load called" not in elsewhere:
        return ctx.failed(
            "The server's debug log of the call is on neither stderr nor in its log file.", evidence
        )
    return ctx.passed("The server still logs every call, away from stdout.", evidence)
