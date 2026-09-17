import socket


def check(ctx):
    ctx.run(["/usr/local/bin/reports-mcp", "restart"])
    listening = ctx.run(["ss", "-Hltn", "sport", "= :8931"]).out
    addresses = [line.split()[3] for line in listening.splitlines() if len(line.split()) > 3]
    outside = ctx.run(["hostname", "-I"]).out.split()
    reachable = []
    for address in outside:
        try:
            socket.create_connection((address, 8931), timeout=1).close()
            reachable.append(address)
        except OSError:
            pass
    evidence = f"listening on :8931: {addresses or 'nothing'}\nreachable on: {reachable or 'none'}"
    if not addresses:
        return ctx.failed("The reports server is not listening at all.", evidence)
    if reachable:
        return ctx.failed(
            f"The reports server answers on {', '.join(reachable)}:8931, around the proxy.",
            evidence,
        )
    return ctx.passed("The reports server listens on loopback only, behind the proxy.", evidence)
