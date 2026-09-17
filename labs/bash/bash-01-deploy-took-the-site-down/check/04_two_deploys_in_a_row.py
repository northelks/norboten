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
        root = os.path.join(base, "www")
        old = os.path.join(root, "releases", "old")
        ctx.write(os.path.join(old, "index.html"), "old\n")
        os.symlink(old, os.path.join(root, "current"))
        a, b = os.path.join(base, "a.tar.gz"), os.path.join(base, "b.tar.gz")
        _archive(a, {"index.html": "A\n", "only-in-a.txt": "A\n"})
        _archive(b, {"index.html": "B\n"})
        env = {"SITE_ROOT": root}
        ra = ctx.run([*IN_PROBE, base, a], env=env, timeout=20)
        rb = ctx.run([*IN_PROBE, base, b], env=env, timeout=20)
        rel_dir = os.path.join(root, "releases")
        releases = sorted(os.listdir(rel_dir))
        current = os.path.join(root, "current")
        evidence = (
            f"first: exit {ra.code} {ra.text}\nsecond: exit {rb.code} {rb.text}\n"
            f"current -> {os.path.realpath(current)}\nreleases: {releases}"
        )
        if ra.code or rb.code:
            return ctx.failed("One of two good deploys failed.", evidence)
        if not os.path.islink(current) or ctx.read(os.path.join(current, "index.html")) != "B\n":
            return ctx.failed("After two deploys, current is not the second release.", evidence)
        new = [r for r in releases if r != "old"]
        if len(new) != 2:
            return ctx.failed("Two deploys did not produce two separate releases.", evidence)
        if os.path.exists(os.path.join(current, "only-in-a.txt")):
            return ctx.failed("The second release contains files from the first.", evidence)
        stray = [
            os.path.join(r, n)
            for r in releases
            for n in os.listdir(os.path.join(rel_dir, r))
            if os.path.islink(os.path.join(rel_dir, r, n))
        ]
        if stray:
            return ctx.failed(
                "A symlink ended up inside a release directory.", evidence + f"\nstray: {stray}"
            )
        return ctx.passed("Two quick deploys made two releases, and the second is live.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
