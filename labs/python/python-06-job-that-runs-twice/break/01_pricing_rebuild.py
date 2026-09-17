"""A rebuild with no lock that writes the live price list product by product."""

import json
import os
import shutil

CATALOGUE = [
    {"sku": "BOLT-M6", "cost": 0.40},
    {"sku": "NUT-M6", "cost": 0.25},
    {"sku": "WASHER-6", "cost": 0.10},
    {"sku": "SPANNER-13", "cost": 6.50},
]


def apply(ctx):
    files = os.path.join(ctx.lab_dir, "files")
    os.makedirs("/opt/pricing", exist_ok=True)
    shutil.copy(os.path.join(files, "rebuild.py"), "/opt/pricing/rebuild.py")
    os.makedirs("/srv/pricing", exist_ok=True)
    ctx.write("/srv/pricing/catalogue.json", json.dumps(CATALOGUE, indent=2) + "\n")
    os.makedirs("/var/lib/pricing", exist_ok=True)
    ctx.write("/var/lib/pricing/prices.json", "{}\n")
    for unit in ("pricing-rebuild.service", "pricing-rebuild.timer"):
        shutil.copy(os.path.join(files, unit), f"/etc/systemd/system/{unit}")
    ctx.run(["systemctl", "daemon-reload"], check=True)
    ctx.run(["systemctl", "enable", "--now", "pricing-rebuild.timer"], check=True)
