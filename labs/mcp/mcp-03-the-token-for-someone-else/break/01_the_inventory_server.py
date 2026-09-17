"""An identity provider, the inventory MCP server set to accept any audience and expired tokens,
and a report job whose token was minted for the billing API and copied across."""

import json
import os
import secrets
import shutil
import sys

sys.path.insert(0, "/usr/local/lib/norboten")
import claude_lab

USER = "learner"
HOME = "/home/learner"
REPO = f"{HOME}/inventory-report"
RESOURCE = "http://127.0.0.1:8931/mcp"
BILLING = "https://billing.example/api"


def lab_file(ctx, name):
    with open(os.path.join(ctx.lab_dir, "files", name)) as f:
        return f.read()


def apply(ctx):
    host = ctx.state.get("host") or f"db-{secrets.token_hex(2)}"
    ctx.state.update(host=host)
    ctx.save_state()

    if not os.path.exists("/etc/lab-idp/signing.key"):
        ctx.write("/etc/lab-idp/signing.key", secrets.token_hex(32) + "\n", mode=0o600)
    ctx.write("/usr/local/bin/lab-idp", lab_file(ctx, "lab-idp"), mode=0o755)
    ctx.write("/opt/inventory-mcp/inventory_mcp.py", lab_file(ctx, "inventory_mcp.py"), mode=0o755)
    ctx.write("/usr/local/bin/inventory-mcp", lab_file(ctx, "inventory-mcp"), mode=0o755)
    hosts = [
        {"name": host, "role": "database", "os": "Ubuntu 26.04"},
        {"name": "web-1", "role": "web", "os": "Ubuntu 26.04"},
        {"name": "legacy-2", "role": "batch", "os": "Ubuntu 20.04"},
    ]
    ctx.write("/var/lib/inventory/hosts.json", json.dumps(hosts, indent=1) + "\n", mode=0o644)
    conf = {"issuer": "https://idp.lab", "audience": None, "verify_exp": False,
            "bind": "127.0.0.1", "port": 8931}  # fmt: skip
    ctx.write("/etc/inventory-mcp/config.json", json.dumps(conf, indent=2) + "\n", mode=0o644)
    ctx.run(["/usr/local/bin/inventory-mcp", "restart"], check=True)

    # "the billing job's token works, use that one"
    token = ctx.run(
        ["/usr/local/bin/lab-idp", "mint", "--audience", BILLING, "--subject", "billing-sync"],
        check=True,
    ).out.strip()
    ctx.write(f"{HOME}/.config/inventory/env", f"INVENTORY_TOKEN={token}\n", mode=0o600)

    shutil.rmtree(REPO, ignore_errors=True)
    mcp = {
        "mcpServers": {
            "inventory": {
                "type": "http",
                "url": RESOURCE,
                "headers": {"Authorization": "Bearer ${INVENTORY_TOKEN}"},
            }
        }
    }
    ctx.write(f"{REPO}/.mcp.json", json.dumps(mcp, indent=2) + "\n")
    ctx.write(f"{HOME}/bin/inventory-report", lab_file(ctx, "inventory-report"), mode=0o755)
    for path in (REPO, f"{HOME}/.config", f"{HOME}/bin"):
        ctx.run(["chown", "-R", f"{USER}:{USER}", path], check=True)

    steps = json.loads(lab_file(ctx, "model.json"))
    claude_lab.run(steps, cwd=REPO, command=[f"{HOME}/bin/inventory-report"], timeout=120)
