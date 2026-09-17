import grp
import pwd


def check(ctx):
    try:
        g = grp.getgrnam("auditors")
    except KeyError:
        return ctx.failed("There is no auditors group.")
    if g.gr_gid != 5000:
        return ctx.failed(f"auditors has GID {g.gr_gid}, not 5000.")
    for name, uid in (("maria", 5001), ("sam", 5002)):
        try:
            u = pwd.getpwnam(name)
        except KeyError:
            return ctx.failed(f"There is no user {name}.")
        if u.pw_uid != uid:
            return ctx.failed(f"{name} has UID {u.pw_uid}, not {uid}.")
        if name not in g.gr_mem and u.pw_gid != 5000:
            return ctx.failed(f"{name} is not a member of auditors.", ", ".join(g.gr_mem))
    return ctx.passed("auditors (5000) exists with maria (5001) and sam (5002) as members.")
