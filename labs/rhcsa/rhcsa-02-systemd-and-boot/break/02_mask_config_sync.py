"""config-sync was masked "temporarily"."""


def apply(ctx):
    ctx.run(["systemctl", "mask", "config-sync.service"], check=True)
