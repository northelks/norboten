"""Applied under old names, renamed in the configuration, a hand-edited file, a readable state."""

import json
import os
import shutil

TF = {"CHECKPOINT_DISABLE": "1", "TF_IN_AUTOMATION": "1", "TF_INPUT": "0"}
INFRA = "/srv/infra"


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    state = os.path.join(INFRA, "terraform.tfstate")
    if not os.path.exists(state):
        os.makedirs(INFRA, exist_ok=True)
        for name in ("versions.tf", "site.conf.tftpl"):
            shutil.copy(os.path.join(files, name), INFRA)
        shutil.copy(os.path.join(files, "main-before.tf"), os.path.join(INFRA, "main.tf"))
        ctx.run(f"cd {INFRA} && terraform init", check=True, timeout=60, env=TF)
        ctx.run(f"cd {INFRA} && terraform apply -auto-approve", check=True, timeout=60, env=TF)
        with open(state) as f:
            data = json.load(f)
        key = next(r for r in data["resources"] if r["type"] == "random_password")
        ctx.state["session_key"] = key["instances"][0]["attributes"]["result"]
        with open("/etc/shop/nginx-site.conf", "a") as f:
            f.write("# incident 2026-09-11: let the office in directly\nallow 203.0.113.0/24;\n")
    shutil.copy(os.path.join(files, "main.tf"), os.path.join(INFRA, "main.tf"))
    for name in ("terraform.tfstate", "terraform.tfstate.backup"):
        if os.path.exists(os.path.join(INFRA, name)):
            os.chmod(os.path.join(INFRA, name), 0o644)
