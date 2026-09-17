"""How much memory each image really needs: the solvability gate, with the guest's memory watched.

    uv run python images/memory.py                          every lab on every image it lists
    uv run python images/memory.py --image alpine --memory alpine=192MiB
    uv run python images/memory.py --lab hello --lab linux-01-disk-full

For each lab × image the gate runs as usual (faults, the checks fail, the solution, check, reboot,
check) while a sampler inside the guest writes MemTotal, MemAvailable and swap in use once a second
to /run. The log is collected before every reboot and before the VM is deleted, together with the
kernel's out-of-memory count. `--memory image=size` gives every lab on that image that much instead
of the registry's min_memory, which is how a proposed floor is proven: the gate must still pass,
with nothing killed.

"Used" is MemTotal − MemAvailable: memory the guest could not hand back without swapping. The
results go to images/out/memory-<timestamp>.json and a table on stdout.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "src"))

from norboten.labs.manifest import LabManifest, default_registry, discover  # noqa: E402
from norboten.lima.instance import Instance  # noqa: E402
from norboten.models import parse_size  # noqa: E402
from norboten.session import gate, guest  # noqa: E402

LOG = "/run/norboten-mem.log"
SAMPLER = f"""#!/bin/sh
while :; do
  awk -v now="$(date +%s)" '
    /^MemTotal:/ {{ t = $2 }} /^MemAvailable:/ {{ a = $2 }}
    /^SwapTotal:/ {{ st = $2 }} /^SwapFree:/ {{ sf = $2 }}
    END {{ print now, t, a, st - sf }}' /proc/meminfo >> {LOG}
  sleep 1
done
"""
MIB = 1024


@dataclass
class Watch:
    # (used KiB, MemTotal KiB, swap in use KiB, the gate step it happened in)
    samples: list[tuple[int, int, int, str]] = field(default_factory=list)
    oom: int = 0

    def collect(self, inst: Instance) -> None:
        """Take the log so far. A sample belongs to the gate step whose marker follows it."""
        r = inst.run(f"cat {LOG} 2>/dev/null; : > {LOG}", sudo=True, user=guest.GRADER, timeout=30)
        pending: list[tuple[int, int, int]] = []
        for line in r.out.splitlines():
            if line.startswith("# "):
                self.samples += [(*s, line[2:]) for s in pending]
                pending = []
                continue
            parts = line.split()
            if len(parts) == 4 and all(p.lstrip("-").isdigit() for p in parts):
                _, total, avail, swap = map(int, parts)
                pending.append((total - avail, total, swap))
        self.samples += [(*s, "until collected") for s in pending]
        k = inst.run(
            "dmesg | grep -ciE 'out of memory|oom-kill'", sudo=True, user=guest.GRADER, timeout=30
        )
        if k.out.strip().isdigit():
            self.oom += int(k.out.strip())


WATCH = Watch()


# Every command goes through the grading account: a lab may take sudo away from the learner
# (rhcsa-05 does, and its log then could not be read back).


def start_sampler(inst: Instance) -> None:
    inst.run(
        "cat > /run/norboten-mem.sh && chmod +x /run/norboten-mem.sh",
        sudo=True,
        user=guest.GRADER,
        input=SAMPLER,
    )
    # through sh: /run is noexec on the systemd images
    inst.run(
        "nohup sh /run/norboten-mem.sh </dev/null >/dev/null 2>&1 &",
        sudo=True,
        user=guest.GRADER,
        timeout=30,
    )


def mark(inst: Instance, step: str) -> None:
    inst.run(f"echo {json.dumps('# ' + step)} >> {LOG}", sudo=True, user=guest.GRADER, timeout=30)


def instrument() -> None:
    """Patch the gate's guest and instance calls, once, so sampling follows the VM through it."""
    install, reboot, delete = guest.install_grader, Instance.reboot, Instance.delete

    def install_grader(inst, learner):
        install(inst, learner)
        start_sampler(inst)

    def reboot_and_sample(self, timeout_s: float = 180) -> bool:
        WATCH.collect(self)
        ok = reboot(self, timeout_s)
        if ok:
            start_sampler(self)
        return ok

    def delete_after_collecting(self) -> None:
        if self.is_running():
            # a VM at a maintenance prompt has no SSH; what was collected before stays
            with contextlib.suppress(Exception):
                WATCH.collect(self)
        delete(self)

    guest.install_grader = install_grader
    Instance.reboot = reboot_and_sample
    Instance.delete = delete_after_collecting


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lab", action="append", default=[])
    ap.add_argument("--image", action="append", default=[])
    ap.add_argument("--memory", action="append", default=[], metavar="IMAGE=SIZE")
    ap.add_argument(
        "--boot-timeout",
        type=int,
        default=0,
        metavar="S",
        help="give up on a boot after S seconds (the gate waits 600; a VM given too little memory "
        "never boots, and waiting that long for each lab says nothing more)",
    )
    args = ap.parse_args()
    if args.boot_timeout:
        start = Instance.start

        def start_briefly(self, timeout_s: int = 600, fast: bool = False) -> None:
            start(self, timeout_s=min(timeout_s, args.boot_timeout), fast=fast)

        Instance.start = start_briefly

    override = {k: parse_size(v) for k, v in (m.split("=", 1) for m in args.memory)}
    registry = default_registry()
    memory_for = LabManifest.memory_for

    def given(self, reg, image_id):
        return override[image_id] if image_id in override else memory_for(self, reg, image_id)

    LabManifest.memory_for = given

    pairs = [
        (lab, image)
        for lab in discover(ROOT / "labs")
        for image in lab.manifest.base_images
        if (not args.lab or lab.id in args.lab) and (not args.image or image in args.image)
    ]
    instrument()
    results = []
    for lab, image in pairs:
        watch = WATCH
        watch.samples, watch.oom = [], 0
        inst = gate._gate_instance(lab, image)

        def say(msg: str, lab=lab, image=image, inst=inst) -> None:
            print(f"  {lab.id} on {image}: {msg}", flush=True)
            with contextlib.suppress(Exception):
                mark(inst, msg.split(" (+")[0])

        memory = lab.manifest.memory_for(registry, image)
        started = time.monotonic()
        try:
            res = gate.validate(lab, image, say=say)
        except Exception as e:  # a boot that timed out: the size is below the floor
            res = gate.GateResult(lab_id=lab.id, image=image, failures=[f"{type(e).__name__}: {e}"])
            with contextlib.suppress(Exception):
                inst.delete()
        peak = max(watch.samples, default=(0, 0, 0, "-"))
        results.append({
            "lab": lab.id, "image": image, "memory_mib": memory // (1024 * 1024),
            "gate_ok": res.ok, "failures": res.failures[:3],
            "mem_total_mib": peak[1] // MIB, "peak_used_mib": peak[0] // MIB, "peak_step": peak[3],
            "swap_peak_mib": max((s[2] for s in watch.samples), default=0) // MIB,
            "oom_kills": watch.oom, "samples": len(watch.samples),
            "seconds": round(time.monotonic() - started),
        })  # fmt: skip
        print(json.dumps(results[-1]), flush=True)

    out = ROOT / "images" / "out" / f"memory-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2) + "\n")

    by_image = defaultdict(list)
    for r in results:
        by_image[r["image"]].append(r)
    head = f"{'image':22} {'given':>7} {'total':>7} {'peak used':>10} {'swap':>5} {'oom':>4}"
    print(f"\n{head}  gate  worst lab")
    for image, rows in by_image.items():
        worst = max(rows, key=lambda r: r["peak_used_mib"])
        print(
            f"{image:22} {worst['memory_mib']:>6}M {worst['mem_total_mib']:>6}M "
            f"{worst['peak_used_mib']:>9}M {max(r['swap_peak_mib'] for r in rows):>4}M "
            f"{sum(r['oom_kills'] for r in rows):>4}  {sum(r['gate_ok'] for r in rows)}/{len(rows)}"
            f"  {worst['lab']} ({worst['peak_step']})"
        )
    print(f"\nwritten to {out.relative_to(ROOT)}")
    return 0 if all(r["gate_ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
