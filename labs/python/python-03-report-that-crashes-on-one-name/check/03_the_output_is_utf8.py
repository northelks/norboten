import os
import shutil
import tempfile


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        members = os.path.join(base, "members")
        os.makedirs(members)
        with open(os.path.join(members, "new.csv"), "w", encoding="utf-8") as f:
            f.write("name,city\nJonas Müller,München\n")
        out = os.path.join(base, "summary.csv")
        # a machine whose locale is not UTF-8: the output encoding must not follow it
        r = ctx.run(
            ["python3", "/opt/members/report.py"],
            env={
                "MEMBERS_DIR": members,
                "SUMMARY_OUT": out,
                "LC_ALL": "C",
                "LANG": "C",
                "PYTHONUTF8": "0",
                "PYTHONCOERCECLOCALE": "0",
            },
            timeout=25,
        )
        raw = None
        if os.path.exists(out):
            with open(out, "rb") as f:
                raw = f.read()
        evidence = f"LC_ALL=C PYTHONUTF8=0\nexit {r.code}\n{r.text}\nbytes: {raw!r}"
        if r.code != 0 or raw is None:
            return ctx.failed("With a non-UTF-8 locale the report fails.", evidence)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return ctx.failed("The summary is not UTF-8 when the locale is not.", evidence)
        if "München" not in text:
            return ctx.failed("The summary lost a city's spelling.", evidence)
        return ctx.passed("The summary is UTF-8 whatever the locale.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
