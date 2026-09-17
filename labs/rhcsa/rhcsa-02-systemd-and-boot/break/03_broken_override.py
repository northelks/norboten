"""A drop-in replaces ExecStart with a path that does not exist."""


def apply(ctx):
    ctx.write(
        "/etc/systemd/system/inventory-api.service.d/override.conf",
        "[Service]\nExecStart=\nExecStart=/usr/local/bin/inventory-api.py\n",
    )
    ctx.run(["systemctl", "daemon-reload"], check=True)
