def check(ctx):
    key = ctx.state["upstream_key"]
    unit = ctx.run(["systemctl", "cat", "chat-gateway"]).text
    shown = ctx.run(["systemctl", "show", "chat-gateway"]).out
    where = []
    if key in unit:
        where.append("the unit definition (systemctl cat)")
    if key in shown:
        where.append("the service's properties (systemctl show)")
    if where:
        return ctx.failed(
            "Any account on the machine can read the upstream key from "
            + " and ".join(where)
            + ".",
            "\n".join(ln for ln in unit.splitlines() if key in ln)[:400],
        )
    return ctx.passed("The upstream key is not part of the unit definition.")
