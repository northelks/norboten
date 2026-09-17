import os
import shutil
import tempfile

# run from inside the probe directory, so a relative path the script makes up stays in it
IN_PROBE = ["sh", "-c", 'cd "$1" && shift && exec /usr/local/bin/deploy-site "$@"', "deploy-site"]


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        root = os.path.join(base, "www")
        old = os.path.join(root, "releases", "old")
        ctx.write(os.path.join(old, "index.html"), "old\n")
        os.symlink(old, os.path.join(root, "current"))
        r = ctx.run([*IN_PROBE, base], env={"SITE_ROOT": root}, timeout=20)
        releases = sorted(os.listdir(os.path.join(root, "releases")))
        target = os.path.realpath(os.path.join(root, "current"))
        evidence = (
            f"exit {r.code}\n"
            f"stdout: {r.out!r}\n"
            f"stderr: {r.err!r}\n"
            f"current -> {target}\n"
            f"releases: {releases}"
        )
        if target != os.path.realpath(old) or releases != ["old"]:
            return ctx.failed("Run with no argument, the script changed the site.", evidence)
        if r.code == 0:
            return ctx.failed("Run with no argument, the script exits 0.", evidence)
        if not r.err.strip():
            return ctx.failed(
                "Run with no argument, the script says nothing on standard error.", evidence
            )
        return ctx.passed("With no argument it explains itself and changes nothing.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
