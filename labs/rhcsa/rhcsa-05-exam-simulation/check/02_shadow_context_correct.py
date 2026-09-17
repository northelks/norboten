def check(ctx):
    pending = ctx.run(
        ["restorecon", "-n", "-v", "/etc/shadow", "/etc/passwd", "/etc/group", "/etc/gshadow"]
    ).out.strip()
    ls = ctx.run(["ls", "-Z", "/etc/shadow"]).out.strip()
    if pending:
        return ctx.failed(
            "Account files have the wrong SELinux label — logins will be denied.",
            f"{ls}\n{pending}",
        )
    return ctx.passed("Account files carry their correct SELinux labels.", ls)
