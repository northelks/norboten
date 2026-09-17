import json
import time


def check(ctx):
    if not (
        ctx.service_enabled("pricing-rebuild.timer") and ctx.service_active("pricing-rebuild.timer")
    ):
        return ctx.failed("pricing-rebuild.timer is not enabled and active.")
    deadline = time.monotonic() + 40
    props = {}
    while time.monotonic() < deadline:
        props = dict(
            line.split("=", 1)
            for line in ctx.run(
                [
                    "systemctl", "show", "pricing-rebuild.service", "-p", "Result",
                    "-p", "ExecMainStatus", "-p", "ExecMainExitTimestampMonotonic",
                ]
            ).out.splitlines()
            if "=" in line
        )  # fmt: skip
        if props.get("ExecMainExitTimestampMonotonic", "0") != "0":
            break
        time.sleep(3)
    log = ctx.run(
        ["journalctl", "-u", "pricing-rebuild.service", "-b", "-n", "12", "--no-pager"]
    ).text
    if props.get("ExecMainExitTimestampMonotonic", "0") == "0":
        return ctx.failed("The timer has not rebuilt the price list since this boot.", log)
    if props.get("Result") != "success" or props.get("ExecMainStatus") != "0":
        return ctx.failed("The last rebuild started by the timer failed.", log)
    text = ctx.read("/var/lib/pricing/prices.json") or ""
    try:
        prices = json.loads(text)
    except ValueError:
        return ctx.failed("The price list on disk is not valid JSON.", f"{text!r}\n{log}")
    catalogue = json.loads(ctx.read("/srv/pricing/catalogue.json") or "[]")
    if sorted(prices) != sorted(item["sku"] for item in catalogue):
        return ctx.failed("The price list does not hold every product.", f"{text!r}\n{log}")
    return ctx.passed("The timer's rebuild succeeded and the price list is complete.", text + log)
