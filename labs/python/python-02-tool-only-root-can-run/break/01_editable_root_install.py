"""netprobe installed editable from root's home into a venv only root can open, not on PATH."""

import os
import shutil


def apply(ctx):
    src = "/root/src/netprobe"
    if not os.path.isdir(src):
        shutil.copytree(os.path.join(ctx.lab_dir, "files", "netprobe"), src)
    os.chmod("/root", 0o700)
    ctx.write(
        "/etc/netprobe/targets.yaml",
        "targets:\n  - 127.0.0.1:22\n  - 127.0.0.1:9\n",
        mode=0o644,
    )
    venv = "/opt/netprobe/venv"
    if not os.path.exists(os.path.join(venv, "bin", "python")):
        ctx.run(["python3", "-m", "venv", venv], check=True)
    ctx.run(
        [
            os.path.join(venv, "bin", "pip"),
            "install",
            "--quiet",
            "--no-index",
            "--find-links",
            "/opt/wheels",
            "--editable",
            src,
        ],
        check=True,
        timeout=110,
    )
    os.chmod(venv, 0o750)
