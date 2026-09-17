"""A team of three with one missing from its group, files only their authors can change, a login
umask that makes every new file private, and a folder anyone can read."""

import os


def _run(ctx, *cmd):
    ctx.run(list(cmd), check=True)


def apply(ctx):
    _run(ctx, "groupadd", "-f", "reports")
    for user in ("alice", "bob", "carol", "dave"):
        if ctx.run(["id", user]).code != 0:
            _run(ctx, "useradd", "--create-home", "--shell", "/bin/bash", user)
    _run(ctx, "usermod", "-aG", "reports", "alice")
    _run(ctx, "usermod", "-aG", "reports", "bob")

    # last year's hardening: every login gets umask 077
    ctx.write(
        "/etc/profile.d/00-hardening.sh", "# security baseline, 2025\numask 077\n", mode=0o644
    )

    ctx.write("/srv/reports/TEAM.txt", "reports team: alice bob carol\n", mode=0o644, owner="alice")
    os.chmod("/srv/reports", 0o755)
    os.chown("/srv/reports", *_ids("alice"))
    for path, owner, mode, text in (
        ("/srv/reports/2026-q3-summary.txt", "alice", 0o600, "Q3: revenue up 4%, costs flat.\n"),
        ("/srv/reports/budget.csv", "bob", 0o644, "item,amount\nservers,1200\nlicences,300\n"),
        ("/srv/reports/drafts/q4-outline.txt", "bob", 0o600, "1. revenue\n2. hiring\n"),
    ):
        ctx.write(path, text, mode=mode, owner=owner, group=owner)
    os.chown("/srv/reports/drafts", *_ids("bob"))
    os.chmod("/srv/reports/drafts", 0o755)


def _ids(user):
    import pwd

    entry = pwd.getpwnam(user)
    return entry.pw_uid, entry.pw_gid
