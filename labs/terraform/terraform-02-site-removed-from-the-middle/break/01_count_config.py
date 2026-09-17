"""Three sites created with count, then blog removed from the middle of the list — not applied."""

import os
import shutil

TF = {"CHECKPOINT_DISABLE": "1", "TF_IN_AUTOMATION": "1", "TF_INPUT": "0"}
SITES = "/srv/sites"


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    if not os.path.exists(os.path.join(SITES, "terraform.tfstate")):
        os.makedirs(SITES, exist_ok=True)
        for name in ("versions.tf", "vhost.conf.tftpl"):
            shutil.copy(os.path.join(files, name), SITES)
        shutil.copy(os.path.join(files, "main-before.tf"), os.path.join(SITES, "main.tf"))
        ctx.run(f"cd {SITES} && terraform init", check=True, timeout=60, env=TF)
        ctx.run(f"cd {SITES} && terraform apply -auto-approve", check=True, timeout=60, env=TF)
        for site in ("shop", "docs"):
            ctx.state[f"{site}_conf"] = ctx.read(f"/etc/nginx-sites/{site}.conf")
    main = os.path.join(SITES, "main.tf")
    text = ctx.read(main) or ""
    ctx.write(main, text.replace('["shop", "blog", "docs"]', '["shop", "docs"]'))
