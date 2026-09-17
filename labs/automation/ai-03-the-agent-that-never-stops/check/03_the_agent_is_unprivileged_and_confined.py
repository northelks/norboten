PROPERTIES = ("User", "DynamicUser", "ProtectSystem", "NoNewPrivileges")


def check(ctx):
    out = ctx.run(
        ["systemctl", "show", "inbox-agent.service", *(f"--property={p}" for p in PROPERTIES)]
    ).out
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    evidence = out.strip()
    if props.get("DynamicUser") != "yes" and props.get("User", "") in ("", "root", "0"):
        return ctx.failed("The agent runs as root.", evidence)
    if props.get("ProtectSystem") not in ("strict", "full"):
        return ctx.failed(
            "The operating system is writable to the agent "
            f"(ProtectSystem={props.get('ProtectSystem')}).",
            evidence,
        )
    if props.get("NoNewPrivileges") != "yes":
        return ctx.failed("The agent could gain privileges through setuid programs.", evidence)
    user = "a dynamic user" if props.get("DynamicUser") == "yes" else props.get("User")
    return ctx.passed(f"The agent runs as {user}, confined.", evidence)
