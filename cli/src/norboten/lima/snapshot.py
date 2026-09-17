"""Disk snapshots with qemu-img, taken and applied while the VM is stopped.

Why not QEMU memory snapshots (savevm/loadvm, what `limactl snapshot` uses on a running VM)?
On Apple Silicon (HVF) with QEMU 11, a guest reboot after `savevm` hangs in UEFI, and starting
QEMU with `-loadvm` aborts in cpu_pre_load. Disk snapshots plus a cold boot are slower but work on
every host, and the golden images are tuned to cold-boot in seconds. See docs/open-questions.md Q13.
"""

from __future__ import annotations

import json
import subprocess

from norboten.host import find_qemu
from norboten.lima.instance import Instance, LimaError

CLEAN = "norboten-clean"


def _qemu_img() -> str:
    q = find_qemu()
    if q is None:
        raise LimaError("qemu-img not found — see System (8) in the TUI")
    return str(q.img)


def _require_stopped(inst: Instance) -> None:
    if inst.is_running():
        raise LimaError(f"{inst.name} must be stopped to snapshot its disks")


def tags(inst: Instance) -> list[str]:
    disks = inst.disk_paths()
    if not disks[0].exists():
        return []
    out = subprocess.run(
        [_qemu_img(), "info", "-U", "--output=json", str(disks[0])],
        capture_output=True,
        text=True,
        check=True,
    )
    return [s["name"] for s in json.loads(out.stdout).get("snapshots", [])]


def create(inst: Instance, tag: str = CLEAN) -> None:
    _require_stopped(inst)
    for disk in inst.disk_paths():
        subprocess.run([_qemu_img(), "snapshot", "-d", tag, str(disk)], capture_output=True)
        subprocess.run(
            [_qemu_img(), "snapshot", "-c", tag, str(disk)], capture_output=True, check=True
        )


def apply(inst: Instance, tag: str = CLEAN) -> None:
    _require_stopped(inst)
    if tag not in tags(inst):
        raise LimaError(f"{inst.name} has no snapshot {tag!r}")
    for disk in inst.disk_paths():
        subprocess.run(
            [_qemu_img(), "snapshot", "-a", tag, str(disk)], capture_output=True, check=True
        )
