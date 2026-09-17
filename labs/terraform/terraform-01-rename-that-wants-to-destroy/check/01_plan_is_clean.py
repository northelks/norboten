TF = {"CHECKPOINT_DISABLE": "1", "TF_IN_AUTOMATION": "1", "TF_INPUT": "0"}


def check(ctx):
    r = ctx.run(
        "cd /srv/infra && terraform plan -detailed-exitcode -lock=false -input=false -no-color",
        timeout=28,
        env=TF,
    )
    tail = r.text[-3500:]
    if r.code == 0:
        return ctx.passed("terraform plan reports no changes.", tail)
    if r.code == 2:
        return ctx.failed("terraform plan still proposes changes.", tail)
    return ctx.failed("terraform plan does not run cleanly.", tail)
