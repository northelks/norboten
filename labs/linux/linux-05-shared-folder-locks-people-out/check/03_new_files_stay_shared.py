import grp
import os
import shlex
import shutil

TEAM = ("alice", "bob", "carol")

FOLDER = "/srv/reports"


def as_user(ctx, user, command):
    """A login shell, as `su -` gives it: the user's groups and umask, as the grader sees them."""
    return ctx.run(["su", "-", user, "-c", command], timeout=30)


def can(ctx, user, test, path):
    return as_user(ctx, user, f"test {test} {shlex.quote(path)}").ok


def check(ctx):
    probe = os.path.join(FOLDER, ".norboten-probe")
    problems, evidence = [], []
    try:
        for author in TEAM[:2]:
            base = f"{probe}-{author}"
            made = as_user(
                ctx, author, f"mkdir {base} && echo draft > {base}/notes.txt && echo x > {base}.txt"
            )
            evidence.append(f"{author} creates: exit {made.code} {made.err.strip()}")
            if not made.ok:
                problems.append(f"{author} cannot create files in {FOLDER}")
                continue
            for path in (base, f"{base}/notes.txt", f"{base}.txt"):
                group = grp.getgrgid(os.stat(path).st_gid).gr_name
                listing = ctx.run(["ls", "-ld", path]).out.strip()
                evidence.append(listing)
                if group != "reports":
                    problems.append(f"what {author} creates belongs to group {group}, not reports")
                    break
                tests = ("-r", "-w", "-x") if os.path.isdir(path) else ("-r", "-w")
                for other in TEAM:
                    if other != author and not all(can(ctx, other, t, path) for t in tests):
                        problems.append(f"{other} cannot change what {author} just created")
                        break
                else:
                    continue
                break
    finally:
        for author in TEAM[:2]:
            shutil.rmtree(f"{probe}-{author}", ignore_errors=True)
            if os.path.exists(f"{probe}-{author}.txt"):
                os.remove(f"{probe}-{author}.txt")
    if problems:
        return ctx.failed(problems[0] + ".", "\n".join(evidence))
    return ctx.passed(
        "New files and directories belong to reports and the rest of the team can change them.",
        "\n".join(evidence),
    )
