"""The motd file exists but has mode 0600."""

import os


def apply(ctx):
    os.makedirs("/srv/example", exist_ok=True)
    ctx.write("/srv/example/motd", "Welcome to the example lab.\n", mode=0o600)
