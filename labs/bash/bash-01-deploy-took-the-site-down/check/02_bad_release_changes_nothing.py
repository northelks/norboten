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
        archive = os.path.join(base, "truncated.tar.gz")
        with open(archive, "wb") as f:
            f.write(b"\x1f\x8b\x08\x00 this archive was cut short")
        r = ctx.run([*IN_PROBE, base, archive], env={"SITE_ROOT": root}, timeout=20)
        releases = sorted(os.listdir(os.path.join(root, "releases")))
        target = os.path.realpath(os.path.join(root, "current"))
        evidence = f"exit {r.code}\n{r.text}\ncurrent -> {target}\nreleases: {releases}"
        if target != os.path.realpath(old):
            return ctx.failed("A corrupt archive replaced the live release.", evidence)
        if r.code == 0:
            return ctx.failed("A corrupt archive was reported as a successful deploy.", evidence)
        if releases != ["old"]:
            return ctx.failed("A failed deploy left a release directory behind.", evidence)
        missing = os.path.join(base, "no-such.tar.gz")
        r2 = ctx.run([*IN_PROBE, base, missing], env={"SITE_ROOT": root}, timeout=20)
        releases = sorted(os.listdir(os.path.join(root, "releases")))
        target = os.path.realpath(os.path.join(root, "current"))
        evidence += (
            f"\n"
            f"\n"
            f"missing archive: exit {r2.code}\n"
            f"{r2.text}\n"
            f"current -> {target}\n"
            f"releases: {releases}"
        )
        if r2.code == 0 or target != os.path.realpath(old) or releases != ["old"]:
            return ctx.failed("A missing archive is not refused cleanly.", evidence)
        return ctx.passed(
            "Corrupt and missing archives are refused and the site stays up.", evidence
        )
    finally:
        shutil.rmtree(base, ignore_errors=True)
