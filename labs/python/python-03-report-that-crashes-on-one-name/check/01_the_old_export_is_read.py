import os
import shutil
import tempfile

UTF8 = "name,city\nAnna Kowalska,Kraków\n"
CP1252 = "name,city\nRuiz Peña,Málaga\n"


def probe(ctx):
    """A directory with one UTF-8 and one cp1252 export, as the real one has."""
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    members = os.path.join(base, "members")
    os.makedirs(members)
    with open(os.path.join(members, "new.csv"), "w", encoding="utf-8") as f:
        f.write(UTF8)
    with open(os.path.join(members, "old.cp1252.csv"), "w", encoding="cp1252") as f:
        f.write(CP1252)
    return base, members, os.path.join(base, "summary.csv")


def run(ctx, members, out, env=None):
    return ctx.run(
        ["python3", "/opt/members/report.py"],
        env={"MEMBERS_DIR": members, "SUMMARY_OUT": out, **(env or {})},
        timeout=25,
    )


def check(ctx):
    base, members, out = probe(ctx)
    try:
        r = run(ctx, members, out)
        summary = ctx.read(out)
        evidence = f"exit {r.code}\n{r.text}\nsummary: {summary!r}"
        if r.code != 0:
            return ctx.failed("The report fails on an export the old tool wrote.", evidence)
        if summary is None or "Málaga" not in summary:
            return ctx.failed("The cp1252 export's cities are not in the summary.", evidence)
        if "Kraków" not in summary:
            return ctx.failed("The UTF-8 export's cities are not in the summary.", evidence)
        return ctx.passed("Both exports were read, each with its own encoding.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
