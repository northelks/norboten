import os
import shlex

TEAM = ("alice", "bob", "carol")


def as_user(ctx, user, command):
    """A login shell, as `su -` gives it: the user's groups and umask, as the grader sees them."""
    return ctx.run(["su", "-", user, "-c", command], timeout=30)


def can(ctx, user, test, path):
    return as_user(ctx, user, f"test {test} {shlex.quote(path)}").ok


def everything(folder="/srv/reports"):
    """Every directory and file under the folder, the folder itself first."""
    out = [folder]
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".norboten-probe"))
        out += [os.path.join(root, d) for d in dirs]
        out += [os.path.join(root, f) for f in sorted(files)]
    return out


def check(ctx):
    problems = []
    for path in everything():
        tests = ("-r", "-w", "-x") if os.path.isdir(path) else ("-r", "-w")
        for user in TEAM:
            denied = [t for t in tests if not can(ctx, user, t, path)]
            if denied:
                what = {"-r": "read", "-w": "write", "-x": "enter"}
                problems.append(f"{user} cannot {'/'.join(what[t] for t in denied)} {path}")
    if problems:
        return ctx.failed(
            f"{len(problems)} thing(s) a team member cannot do in /srv/reports.",
            "\n".join(problems[:15]),
        )
    return ctx.passed("Every team member can read and change everything in /srv/reports.")
