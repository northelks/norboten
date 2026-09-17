"""The default target was changed."""


def apply(ctx):
    ctx.run(["systemctl", "set-default", "graphical.target"], check=True)
