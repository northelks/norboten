"""An enforcing profile that still points at the old data directory."""

import os
import shutil


def apply(ctx):
    dst = "/etc/apparmor.d/usr.local.bin.notes-app"
    shutil.copy(os.path.join(ctx.lab_dir, "files", "usr.local.bin.notes-app"), dst)
    ctx.run(["apparmor_parser", "-r", dst], check=True)
