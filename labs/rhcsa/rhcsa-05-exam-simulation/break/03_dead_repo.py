"""The only enabled repository points at a mirror that does not exist."""

import glob
import re


def apply(ctx):
    for repo in glob.glob("/etc/yum.repos.d/*.repo"):
        text = ctx.read(repo) or ""
        ctx.write(repo, re.sub(r"^enabled\s*=\s*1", "enabled=0", text, flags=re.M))
    ctx.write(
        "/etc/yum.repos.d/lab-local.repo",
        "[lab-local]\nname=Lab packages\nbaseurl=http://mirror.lab.invalid/rocky10/\n"
        "enabled=1\ngpgcheck=0\n",
    )
