"""The deploy script without error handling, quoting or unique release names, and a live site."""

import os
import shutil
import tarfile
import tempfile


def apply(ctx):
    shutil.copy(os.path.join(ctx.lab_dir, "files", "deploy-site"), "/usr/local/bin/deploy-site")
    os.chmod("/usr/local/bin/deploy-site", 0o755)
    release = "/srv/www/releases/20260912083000"
    ctx.write(os.path.join(release, "index.html"), "<h1>Shop</h1>\n<p>Release 2026-09-12</p>\n")
    ctx.write(os.path.join(release, "status.json"), '{"release": "20260912083000"}\n')
    if not os.path.islink("/srv/www/current"):
        os.symlink(release, "/srv/www/current")
    tmp = tempfile.mkdtemp()
    try:
        ctx.write(os.path.join(tmp, "index.html"), "<h1>Shop</h1>\n<p>Release 2026-09-13</p>\n")
        with tarfile.open("/root/release-2026-09-13.tar.gz", "w:gz") as tar:
            tar.add(os.path.join(tmp, "index.html"), arcname="index.html")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
