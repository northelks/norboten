import os
import shutil
import stat
import tempfile


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        tmpl, values, out = (os.path.join(base, n) for n in ("app.tmpl", "values.env", "app.conf"))
        ctx.write(tmpl, "host = @DB_HOST@\npassword = @DB_PASSWORD@\n")
        ctx.write(values, "DB_HOST=db\nDB_PASSWORD=plain\n")
        env = {"RENDER_TEMPLATE": tmpl, "RENDER_VALUES": values, "RENDER_OUT": out}
        r = ctx.run(["sh", "-c", "umask 022; exec render-config"], env=env, timeout=20)
        mode = stat.S_IMODE(os.stat(out).st_mode) if os.path.exists(out) else None
        live = "/etc/myapp/app.conf"
        live_mode = stat.S_IMODE(os.stat(live).st_mode) if os.path.exists(live) else None
        evidence = (
            f"exit {r.code}\n{r.text}\nrendered with umask 022: mode "
            f"{'missing' if mode is None else f'{mode:04o}'}\n"
            f"{live}: {'missing' if live_mode is None else f'{live_mode:04o}'}"
        )
        if mode is None:
            return ctx.failed("The render wrote no file.", evidence)
        if mode & 0o077:
            return ctx.failed(
                "A rendered configuration can be read by others than its owner.", evidence
            )
        if live_mode is not None and live_mode & 0o077:
            return ctx.failed(f"{live} can be read by others than its owner.", evidence)
        return ctx.passed("The rendered configuration is readable by its owner only.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
