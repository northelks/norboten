import os

OUTSIDER = "dave"

FOLDER = "/srv/reports"


def as_user(ctx, user, command):
    """A login shell, as `su -` gives it: the user's groups and umask, as the grader sees them."""
    return ctx.run(["su", "-", user, "-c", command], timeout=30)


def everything(folder="/srv/reports"):
    """Every directory and file under the folder, the folder itself first."""
    out = [folder]
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".norboten-probe"))
        out += [os.path.join(root, d) for d in dirs]
        out += [os.path.join(root, f) for f in sorted(files)]
    return out


def check(ctx):
    listing = as_user(ctx, OUTSIDER, f"ls {FOLDER}")
    readable = [
        p
        for p in everything()
        if os.path.isfile(p) and as_user(ctx, OUTSIDER, f"cat '{p}' >/dev/null").ok
    ]
    evidence = f"ls as dave: exit {listing.code}\nreadable by dave: {', '.join(readable) or 'none'}"
    if listing.ok:
        return ctx.failed("dave can list /srv/reports.", evidence)
    if readable:
        return ctx.failed(f"dave can read {len(readable)} file(s).", evidence)
    return ctx.passed("dave can neither list the folder nor read anything in it.", evidence)
