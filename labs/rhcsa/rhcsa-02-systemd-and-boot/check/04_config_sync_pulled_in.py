def check(ctx):
    deps = ctx.run(
        ["systemctl", "show", "-p", "Wants", "-p", "Requires", "-p", "BindsTo", "inventory-api"]
    ).out
    pulled = "config-sync.service" in deps or ctx.service_enabled("config-sync")
    active = ctx.service_active("config-sync")
    evidence = f"{deps.strip()}\nconfig-sync active: {active}"
    if not pulled:
        return ctx.failed(
            "Nothing makes systemd start config-sync; the API only waits for it if it happens "
            "to run.",
            evidence,
        )
    if not active:
        return ctx.failed("config-sync has not run in this boot.", evidence)
    return ctx.passed("config-sync is pulled in and has run.", evidence)
