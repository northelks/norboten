"""kmorris's login profile sets umask 077."""


def apply(ctx):
    home = ctx.run(["getent", "passwd", "kmorris"], check=True).out.split(":")[5]
    profile = f"{home}/.bash_profile"
    text = ctx.read(profile) or ""
    if "umask 077" not in text:
        ctx.write(
            profile,
            text.rstrip("\n") + "\n\n# set during onboarding\numask 077\n",
            mode=0o644,
            owner="kmorris",
            group="kmorris",
        )
