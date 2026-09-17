import os
import shutil
import tempfile

PREVIOUS = "host = db\npassword = the-old-one\n"


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        tmpl, values, out = (os.path.join(base, n) for n in ("app.tmpl", "values.env", "app.conf"))
        ctx.write(tmpl, "host = @DB_HOST@\npassword = @DB_PASSWORD@\n")
        ctx.write(values, "DB_PASSWORD=new-one\n")  # DB_HOST is missing
        ctx.write(out, PREVIOUS, mode=0o600)
        env = {"RENDER_TEMPLATE": tmpl, "RENDER_VALUES": values, "RENDER_OUT": out}
        r = ctx.run(["env", "-u", "DB_HOST", "render-config"], env=env, timeout=20)
        after = ctx.read(out)
        evidence = (
            f"values without DB_HOST\nexit {r.code}\nstdout: {r.out!r}\nstderr: {r.err!r}\n"
            f"configuration now: {after!r}"
        )
        if r.code == 0:
            return ctx.failed("A missing value is rendered as if nothing were wrong.", evidence)
        if "DB_HOST" not in r.err:
            return ctx.failed("The error does not name the missing value.", evidence)
        if after != PREVIOUS:
            return ctx.failed("A failed render replaced the previous configuration.", evidence)
        return ctx.passed("A missing value fails, is named, and changes nothing.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
