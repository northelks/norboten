import os
import shutil
import tempfile

VALUES = {
    "DB_HOST": "db-2.internal:5432/app",
    "DB_PASSWORD": r"a/b&c\d$e|f#g%h*i~j\1k&&",
}
TEMPLATE = "host = @DB_HOST@\npassword = @DB_PASSWORD@\nagain = @DB_PASSWORD@\n"


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        tmpl, values, out = (os.path.join(base, n) for n in ("app.tmpl", "values.env", "app.conf"))
        ctx.write(tmpl, TEMPLATE)
        ctx.write(values, "".join(f"{k}='{v}'\n" for k, v in VALUES.items()))
        env = {"RENDER_TEMPLATE": tmpl, "RENDER_VALUES": values, "RENDER_OUT": out}
        r = ctx.run(["render-config"], env=env, timeout=20)
        want = TEMPLATE
        for key, value in VALUES.items():
            want = want.replace(f"@{key}@", value)
        got = ctx.read(out)
        evidence = f"values:\n{ctx.read(values)}exit {r.code}\n{r.text}\nrendered:\n{got}"
        if r.code != 0:
            return ctx.failed("Values with special characters make the render fail.", evidence)
        if got != want:
            return ctx.failed(
                "A value with special characters is not rendered literally.", evidence
            )
        return ctx.passed("Every value is rendered exactly, special characters and all.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
