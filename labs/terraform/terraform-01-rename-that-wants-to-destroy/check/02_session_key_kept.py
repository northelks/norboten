import json


def check(ctx):
    original = ctx.state["session_key"]
    try:
        with open("/srv/infra/terraform.tfstate") as f:
            state = json.load(f)
    except (OSError, ValueError) as e:
        return ctx.failed("The state file cannot be read.", str(e))
    addresses = {f"{r['type']}.{r['name']}": r for r in state.get("resources", [])}
    evidence = "resources in state: " + ", ".join(sorted(addresses))
    key = addresses.get("random_password.session_key")
    if key is None or "local_file.app_env" not in addresses:
        return ctx.failed("The state does not track the resources under their new names.", evidence)
    if key["instances"][0]["attributes"].get("result") != original:
        return ctx.failed("The session key in the state is not the original one.", evidence)
    env = ctx.read("/etc/shop/app.env") or ""
    if f"SESSION_KEY={original}" not in env.splitlines():
        return ctx.failed("/etc/shop/app.env does not carry the original session key.", evidence)
    return ctx.passed("The original session key survived the rename.", evidence)
