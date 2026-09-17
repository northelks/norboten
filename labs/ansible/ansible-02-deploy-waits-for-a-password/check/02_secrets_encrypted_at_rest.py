import os

VAULT = "/srv/deploy/group_vars/app/vault.yml"


def check(ctx):
    password = ctx.state["db_password"]
    head = (ctx.read(VAULT) or "").splitlines()[:1]
    if not head or not head[0].startswith("$ANSIBLE_VAULT;"):
        return ctx.failed(f"{VAULT} is not encrypted.", f"first line: {head}")
    found = []
    for root, dirs, files in os.walk("/srv/deploy"):
        dirs[:] = [d for d in dirs if d != ".git"]
        for name in files:
            path = os.path.join(root, name)
            try:
                with open(path, "rb") as f:
                    if password.encode() in f.read(1 << 20):
                        found.append(path)
            except OSError:
                continue
    if found:
        return ctx.failed("The database password is stored in plain text.", "\n".join(found))
    return ctx.passed("The vault file is encrypted and no plain copy is left.", head[0])
