"""The nginx restart rule names %ops instead of %devops."""


def apply(ctx):
    rule = "%ops ALL=(root) NOPASSWD: /usr/bin/systemctl restart nginx\n"
    ctx.write("/etc/sudoers.d/devops", rule, mode=0o440)
    ctx.run(["visudo", "-cf", "/etc/sudoers.d/devops"], check=True)
