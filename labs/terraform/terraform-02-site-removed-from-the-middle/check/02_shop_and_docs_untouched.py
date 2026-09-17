TF = {"CHECKPOINT_DISABLE": "1", "TF_IN_AUTOMATION": "1", "TF_INPUT": "0"}


def check(ctx):
    changed = []
    for site in ("shop", "docs"):
        if ctx.read(f"/etc/nginx-sites/{site}.conf") != ctx.state[f"{site}_conf"]:
            changed.append(site)
    if changed:
        now = "\n".join(
            f"--- {s}.conf now:\n{ctx.read(f'/etc/nginx-sites/{s}.conf')}" for s in changed
        )
        return ctx.failed(f"Changed since the blog was retired: {', '.join(changed)}.", now)
    r = ctx.run(
        "cd /srv/sites && terraform plan -detailed-exitcode -lock=false -input=false -no-color",
        timeout=28,
        env=TF,
    )
    tail = r.text[-3500:]
    if r.code == 2:
        return ctx.failed("terraform plan still proposes changes.", tail)
    if r.code != 0:
        return ctx.failed("terraform plan does not run cleanly.", tail)
    return ctx.passed("shop and docs are unchanged and the plan is clean.", tail)
