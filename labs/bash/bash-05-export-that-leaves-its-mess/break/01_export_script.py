"""An export that writes its final name directly, shares /tmp/export.tmp and never cleans up."""

import os
import shutil


def apply(ctx):
    shutil.copy(os.path.join(ctx.lab_dir, "files", "export-orders"), "/usr/local/bin/export-orders")
    os.chmod("/usr/local/bin/export-orders", 0o755)
    ctx.write("/srv/orders/morning.csv", "id,sku,qty\n1001,BOLT-M6,40\n1002,NUT-M6,40\n")
    ctx.write("/srv/orders/afternoon.csv", "id,sku,qty\n1003,WASHER-6,200\n")
    os.makedirs("/srv/exports", exist_ok=True)
