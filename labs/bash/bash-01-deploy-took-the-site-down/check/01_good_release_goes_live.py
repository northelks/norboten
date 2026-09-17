import io
import os
import shutil
import tarfile
import tempfile

# run from inside the probe directory, so a relative path the script makes up stays in it
IN_PROBE = ["sh", "-c", 'cd "$1" && shift && exec /usr/local/bin/deploy-site "$@"', "deploy-site"]


def _archive(path, files):
    with tarfile.open(path, "w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))


def check(ctx):
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        root = os.path.join(base, "web root")
        old = os.path.join(root, "releases", "old")
        ctx.write(os.path.join(old, "index.html"), "old\n")
        os.symlink(old, os.path.join(root, "current"))
        archive = os.path.join(base, "new release.tar.gz")
        _archive(archive, {"index.html": "new\n", "css/site.css": "body{}\n"})
        r = ctx.run([*IN_PROBE, base, archive], env={"SITE_ROOT": root}, timeout=20)
        live = os.path.join(root, "current", "index.html")
        served = ctx.read(live)
        evidence = (
            f"exit {r.code}\n{r.text}\ncurrent -> {os.path.realpath(os.path.join(root, 'current'))}"
        )
        if r.code != 0:
            return ctx.failed(
                "A good archive, with a space in SITE_ROOT, did not deploy.", evidence
            )
        if served != "new\n" or ctx.read(os.path.join(root, "current", "css", "site.css")) is None:
            return ctx.failed(
                "After a successful deploy, current does not serve the new release.", evidence
            )
        if os.path.realpath(os.path.join(root, "current")) == os.path.realpath(old):
            return ctx.failed("current still points at the previous release.", evidence)
        return ctx.passed("A good archive went live, spaces and all.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
