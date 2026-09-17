"""/srv/project is group devops, mode 0750: no setgid, no group write."""

import os


def apply(ctx):
    os.makedirs("/srv/project", exist_ok=True)
    ctx.write(
        "/srv/project/README",
        "Shared devops workspace.\n",
        mode=0o644,
        owner="apatel",
        group="devops",
    )
    ctx.write(
        "/srv/project/deploy.sh",
        "#!/bin/sh\necho deploying\n",
        mode=0o755,
        owner="apatel",
        group="devops",
    )
    ctx.run(["chown", "root:devops", "/srv/project"], check=True)
    os.chmod("/srv/project", 0o750)
