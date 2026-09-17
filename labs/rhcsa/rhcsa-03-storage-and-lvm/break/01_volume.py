"""vg0 on /dev/vdb with one LV using every extent, XFS, mounted at /var/lib/app, full of data."""

import hashlib
import os

MOUNT = "/var/lib/app"


def _head_hash(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read(1 << 20)).hexdigest()


def apply(ctx):
    if not ctx.run(["vgs", "vg0"]).ok:
        ctx.run(["pvcreate", "-y", "/dev/vdb"], check=True)
        ctx.run(["vgcreate", "vg0", "/dev/vdb"], check=True)
        ctx.run(["lvcreate", "-y", "-n", "applv", "-l", "100%FREE", "vg0"], check=True)
        ctx.run(["mkfs.xfs", "-q", "/dev/vg0/applv"], check=True)
    os.makedirs(MOUNT, exist_ok=True)
    uuid = ctx.run(["blkid", "-s", "UUID", "-o", "value", "/dev/vg0/applv"], check=True).out.strip()
    fstab = ctx.read("/etc/fstab") or ""
    if MOUNT not in fstab:
        line = f"UUID={uuid} {MOUNT} xfs defaults,x-systemd.device-timeout=10s 0 0\n"
        ctx.write("/etc/fstab", fstab.rstrip("\n") + "\n" + line)
        ctx.run(["systemctl", "daemon-reload"], check=True)
    if not os.path.ismount(MOUNT):
        ctx.run(["mount", MOUNT], check=True)
    data = os.path.join(MOUNT, "data")
    os.makedirs(data, exist_ok=True)
    orders = os.path.join(data, "orders.db")
    if not os.path.exists(orders):
        ctx.run(["fallocate", "-l", "1400M", orders], check=True)
        with open(orders, "r+b") as f:
            f.write(
                os.urandom(1 << 20)
            )  # a unique head, so the checks can tell it is the same file
        ctx.write(os.path.join(data, "customers.db"), os.urandom(4096).hex())
    ctx.state["orders_size"] = os.path.getsize(orders)
    ctx.state["orders_head"] = _head_hash(orders)
    ctx.state["customers_size"] = os.path.getsize(os.path.join(data, "customers.db"))
