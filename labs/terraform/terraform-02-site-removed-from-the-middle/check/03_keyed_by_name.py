import json


def check(ctx):
    try:
        with open("/srv/sites/terraform.tfstate") as f:
            state = json.load(f)
    except (OSError, ValueError) as e:
        return ctx.failed("The state file cannot be read.", str(e))
    lines, positional = [], []
    for r in state.get("resources", []):
        if r.get("mode") != "managed":
            continue
        for i in r.get("instances", []):
            key = i.get("index_key")
            address = f"{r['type']}.{r['name']}" + (f"[{key!r}]" if key is not None else "")
            lines.append(address)
            if not isinstance(key, str):
                positional.append(address)
    evidence = "\n".join(lines)
    if not lines:
        return ctx.failed("The state tracks no resources.", evidence)
    if positional:
        return ctx.failed("Some site resources are identified by position, not by name.", evidence)
    keys = {line.split("[", 1)[1] for line in lines}
    if keys != {"'shop']", "'docs']"}:
        return ctx.failed("The resources are not keyed by the site names shop and docs.", evidence)
    return ctx.passed("Every site resource is keyed by the site's name.", evidence)
