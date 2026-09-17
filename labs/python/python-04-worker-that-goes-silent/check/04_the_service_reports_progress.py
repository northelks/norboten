import time


def check(ctx):
    if not (ctx.service_enabled("ingest.service") and ctx.service_active("ingest.service")):
        status = ctx.run(["systemctl", "status", "--no-pager", "-n", "8", "ingest.service"]).text
        return ctx.failed("ingest.service is not enabled and running.", status)
    marker = f"probe-{int(time.time())}.txt"
    ctx.write(f"/srv/ingest/queue/{marker}", "1.00\n")
    deadline = time.monotonic() + 20
    log = ""
    try:
        while time.monotonic() < deadline:
            log = ctx.run(
                ["journalctl", "-u", "ingest.service", "-b", "-n", "20", "--no-pager"]
            ).text
            if f"ingested {marker}" in log:
                return ctx.passed("The service reported a new file in the journal.", log)
            time.sleep(2)
    finally:
        ctx.run(["rm", "-f", f"/srv/ingest/queue/{marker}"])
    ledger = ctx.read("/var/lib/ingest/ledger.csv") or ""
    if marker in ledger:
        return ctx.failed(
            "The file was ingested, and the journal was told nothing about it.", f"{log}\n{ledger}"
        )
    return ctx.failed("The service did not ingest a file dropped into the queue.", log)
