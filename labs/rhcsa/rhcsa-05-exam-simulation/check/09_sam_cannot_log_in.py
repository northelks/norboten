import pwd


def check(ctx):
    try:
        shell = pwd.getpwnam("sam").pw_shell
    except KeyError:
        return ctx.failed("There is no user sam.")
    if shell not in ("/sbin/nologin", "/usr/sbin/nologin", "/bin/false", "/usr/bin/false"):
        return ctx.failed(f"sam's shell is {shell}, which allows an interactive login.")
    return ctx.passed(f"sam cannot log in interactively ({shell}).")
