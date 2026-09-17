import json
import os


def check(ctx):
    try:
        with open("/srv/sites/terraform.tfstate") as f:
            state = json.load(f)
    except (OSError, ValueError) as e:
        return ctx.failed("The state file cannot be read.", str(e))
    blog = [
        f"{r['type']}.{r['name']}[{i.get('index_key')!r}]"
        for r in state.get("resources", [])
        for i in r.get("instances", [])
        if "blog" in json.dumps(i.get("attributes", {})) or i.get("index_key") == "blog"
    ]
    exists = os.path.exists("/etc/nginx-sites/blog.conf")
    evidence = f"blog.conf exists: {exists}\nblog in state: {blog}"
    if exists:
        return ctx.failed("blog.conf is still there.", evidence)
    if blog:
        return ctx.failed("The state still tracks something for the blog.", evidence)
    return ctx.passed("The blog is gone from disk and from the state.", evidence)
