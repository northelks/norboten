"""Per-lab lima.yaml generation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from norboten.models import Arch

ROOT_DISK_GIB = 12


def root_disk_gib(image: Path) -> int:
    """At least ROOT_DISK_GIB, and never smaller than the image itself: Lima cannot shrink."""
    try:
        out = subprocess.run(
            ["qemu-img", "info", "-U", "--output=json", str(image)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        virtual = json.loads(out)["virtual-size"]
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError):
        return ROOT_DISK_GIB
    return max(ROOT_DISK_GIB, -(-virtual // 1024**3))


def render(
    *,
    arch: Arch,
    image: Path,
    cpus: int,
    memory_bytes: int,
    extra_disks: int = 0,
    instance: str,
    user: str | None = None,
) -> dict:
    """A Lima config for one lab VM.

    plain mode: no host mounts, no port forwarding, no containerd. The learner's home directory is
    never visible inside a lab VM, and nothing in the guest reaches the host except over SSH.
    """
    config: dict = {
        "vmType": "qemu",
        "arch": arch.value,
        "images": [{"location": str(image), "arch": arch.value}],
        "cpus": cpus,
        "memory": f"{memory_bytes // (1024 * 1024)}MiB",
        "disk": f"{root_disk_gib(image)}GiB",
        "plain": True,
        "mounts": [],
        "video": {"display": "none"},
        "ssh": {"localPort": 0, "loadDotSSHPubKeys": False, "forwardAgent": False},
        "firmware": {"legacyBIOS": False},
    }
    if extra_disks:
        config["additionalDisks"] = [
            {"name": f"{instance}-d{i}", "format": False} for i in range(1, extra_disks + 1)
        ]
    if user:
        config["user"] = {"name": user}
    return config
