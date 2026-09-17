import os
import shutil
import tempfile

NAMES = ["Ruiz Peña", "Anaïs Fabre", "Søren Ødegård", "François Lefèvre"]


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        members = os.path.join(base, "members")
        os.makedirs(members)
        with open(os.path.join(members, "old.cp1252.csv"), "w", encoding="cp1252") as f:
            f.write("name,city\n" + "".join(f"{n},Málaga\n" for n in NAMES[:2]))
        with open(os.path.join(members, "new.csv"), "w", encoding="utf-8") as f:
            f.write("name,city\n" + "".join(f"{n},Oslo\n" for n in NAMES[2:]))
        out = os.path.join(base, "summary.csv")
        r = ctx.run(
            ["python3", "/opt/members/report.py"],
            env={"MEMBERS_DIR": members, "SUMMARY_OUT": out},
            timeout=25,
        )
        summary = ctx.read(out) or ""
        evidence = f"exit {r.code}\n{r.text}\nsummary: {summary!r}"
        if r.code != 0:
            return ctx.failed("The report fails on these exports.", evidence)
        missing = [n for n in NAMES if n not in summary]
        if missing:
            return ctx.failed(
                f"{len(missing)} of {len(NAMES)} names are missing or changed in the summary.",
                evidence + f"\nmissing: {missing}",
            )
        for bad in ("�", "?,", "Pea", "Anas"):
            if bad in summary:
                return ctx.failed(
                    "A name reached the summary with characters replaced or dropped.", evidence
                )
        return ctx.passed("Every name is in the summary exactly as it was written.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
