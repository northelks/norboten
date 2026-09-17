import os
import sys

SNIPPET = (
    "import calendar, json, logging, sys;"
    "print(calendar.__file__);print(json.__file__);print(logging.__file__);"
    "print(calendar.monthrange(2026, 9)[1])"
)


def check(ctx):
    r = ctx.run(["sh", "-c", 'cd /opt/digest && exec python3 -c "$1"', "sh", SNIPPET], timeout=25)
    lines = r.out.split()
    named = sorted(
        p
        for p in os.listdir("/opt/digest")
        if p.endswith(".py") and p[:-3] in sys.stdlib_module_names
    )
    evidence = f"python3 -c in /opt/digest\nexit {r.code}\n{r.text}\nstdlib-named files: {named}"
    if r.code != 0 or len(lines) != 4:
        return ctx.failed("Importing the standard library from /opt/digest fails.", evidence)
    shadowed = [p for p in lines[:3] if p.startswith("/opt/digest")]
    if shadowed or named:
        return ctx.failed(
            "A file in /opt/digest stands in for a standard library module.", evidence
        )
    if lines[3] != "30":
        return ctx.failed("calendar.monthrange does not answer for September 2026.", evidence)
    return ctx.passed("The standard library modules come from the standard library.", evidence)
