def check(ctx):
    # Only this invocation of the service: what leaked before the fix is not held against it.
    invocation = ctx.run(
        ["systemctl", "show", "-p", "InvocationID", "--value", "chat-gateway"]
    ).out.strip()
    if not invocation:
        return ctx.failed("The gateway is not running, so there is nothing to judge.")
    log = ctx.run(
        ["journalctl", f"_SYSTEMD_INVOCATION_ID={invocation}", "--no-pager", "-n", "500"]
    ).out
    leaked = [
        name
        for name, secret in (
            ("the upstream key", ctx.state["upstream_key"]),
            ("a client token", ctx.state["client_token"]),
        )
        if secret in log
    ]
    if leaked:
        lines = [
            ln
            for ln in log.splitlines()
            if ctx.state["upstream_key"] in ln or ctx.state["client_token"] in ln
        ]
        return ctx.failed(
            "Since its last start, the gateway logged " + " and ".join(leaked) + ".",
            "\n".join(lines)[:400],
        )
    return ctx.passed("The gateway's log for this run holds no secrets.")
