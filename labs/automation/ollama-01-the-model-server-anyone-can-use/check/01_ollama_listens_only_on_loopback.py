LOOPBACK = ("127.0.0.1:", "[::1]:")


def check(ctx):
    status = ctx.run(["systemctl", "status", "--no-pager", "-n", "5", "ollama"]).text
    if not ctx.service_enabled("ollama") or not ctx.service_active("ollama"):
        return ctx.failed("ollama is not running and enabled at boot.", status)
    sockets = ctx.run(["ss", "-Hltn"]).out.splitlines()
    ours = [
        line.split()[3]
        for line in sockets
        if len(line.split()) > 3 and line.split()[3].endswith(":11434")
    ]
    evidence = "listening on port 11434: " + (", ".join(ours) or "nothing")
    if not ours:
        return ctx.failed("Nothing listens on port 11434.", evidence)
    exposed = [a for a in ours if not a.startswith(LOOPBACK)]
    if exposed:
        return ctx.failed(
            f"Ollama listens on {', '.join(exposed)}, reachable from the network.", evidence
        )
    return ctx.passed("Ollama listens on loopback only.", evidence)
