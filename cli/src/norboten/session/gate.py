"""The solvability gate — docs/lab-spec.md section 9.

    clean VM -> faults -> every check fails -> reference solution -> check, reboot, check: all pass
    boot_after_break labs, again: clean VM -> faults -> boot -> every check still fails

A lab that cannot be solved by its own solution cannot merge. Runs in a throwaway VM that never
touches the learner's sessions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from norboten import containers
from norboten.containers import Container
from norboten.host import host_arch
from norboten.images import store
from norboten.labs.manifest import Lab, default_registry
from norboten.lima import install, template
from norboten.lima.instance import Instance
from norboten.models import Phase
from norboten.session import guest
from norboten.session.engine import Say, _quiet


@dataclass
class GateResult:
    lab_id: str
    image: str
    ok: bool = False
    failures: list[str] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)

    def fail(self, msg: str) -> None:
        self.failures.append(msg)


def _gate_instance(lab: Lab, image_id: str) -> Instance | Container:
    name = f"lg-{lab.manifest.short_id}-{image_id}"
    if lab.manifest.runtime == "container":
        return Container(name)
    return Instance(name, admin_user=guest.GRADER)


def validate(lab: Lab, image_id: str, say: Say = _quiet, keep: bool = False) -> GateResult:
    m = lab.manifest
    res = GateResult(lab_id=m.id, image=image_id)
    inst = _gate_instance(lab, image_id)
    t0 = time.monotonic()

    def step(name: str) -> None:
        res.timings[name] = round(time.monotonic() - t0, 1)
        say(f"{name} (+{res.timings[name]:.0f}s)")

    if inst.exists():
        inst.delete()
    registry = default_registry()
    config: dict = {}
    if isinstance(inst, Container):
        image = registry.get(image_id)
        assert image.container is not None
        containers.build(image)
        inst.create(
            image.container.tag,
            memory_bytes=m.memory_for(registry, image_id),
            cpus=m.resources.cpus,
        )
    else:
        install.install()
        img = store.pull(image_id)
        config = template.render(
            arch=host_arch(),
            image=img.path,
            cpus=m.resources.cpus,
            memory_bytes=m.memory_for(registry, image_id),
            extra_disks=len(m.resources.disks),
            instance=inst.name,
        )
        inst.create(config, extra_disks=[d.size for d in m.resources.disks])
    try:
        inst.start(timeout_s=600)
        learner = inst.run("id -un").out.strip()
        if isinstance(inst, Container):
            step("started a clean container")
        else:
            guest.install_grader(inst, learner)
            step("booted a clean VM")

        guest.apply_faults(inst, lab, learner)
        step("applied the faults")

        broken = {r["id"]: r for r in guest.run_checks(inst, lab, "pre_reboot", learner)}
        for c in m.checks:
            r = broken.get(c.id)
            if r is None:
                res.fail(f"{c.id}: produced no result on the broken system")
            elif r["passed"] and not c.baseline_pass:
                res.fail(
                    f"{c.id}: PASSES on the broken system — it does not test the fault "
                    f"({r['message']})"
                )
        step("every check fails on the broken system" if not res.failures else "broken-state run")

        sol = guest.run_solution(inst, lab, image_id, learner)
        if not sol.ok:
            res.fail(f"reference solution exited {sol.code}: {(sol.err or sol.out).strip()[-800:]}")
            return res
        step("ran the reference solution")

        phases = [Phase.PRE_REBOOT] + ([Phase.POST_REBOOT] if m.reboot_required else [])
        for phase in phases:
            if phase is Phase.POST_REBOOT:
                if not inst.reboot(timeout_s=420):
                    res.fail("the solved system did not come back after a reboot")
                    res.fail("console tail:\n" + inst.serial_tail(1500))
                    return res
                step("rebooted")
            for r in guest.run_checks(inst, lab, phase.value, learner):
                if not r["passed"]:
                    res.fail(f"{r['id']}: fails after the solution ({phase.value}): {r['message']}")
            step(f"checked ({phase.value})")
        if m.boot_after_break and not res.failures:
            _after_the_break_boot(lab, inst, config, res, step)
        res.ok = not res.failures
        return res
    finally:
        if not keep:
            inst.delete()


def _after_the_break_boot(lab: Lab, inst: Instance, config: dict, res: GateResult, step) -> None:
    """Q18: the learner meets the machine after one more boot, so every fault must survive it.

    A fresh VM gets the faults, boots once more exactly as a learner's would, and every check must
    still fail. The checks travel over SSH when the broken machine has a network, and over the
    serial console, as root, when it stopped at a maintenance prompt.
    """
    m = lab.manifest
    inst.delete()
    inst.create(config, extra_disks=[d.size for d in m.resources.disks])
    inst.start(timeout_s=600)
    learner = inst.run("id -un").out.strip()
    guest.install_grader(inst, learner)
    guest.apply_faults(inst, lab, learner)
    debug_shell = guest.open_debug_shell(inst)
    outcome = guest.reboot_into_broken(inst)
    step(f"booted into the broken system ({outcome})")
    if outcome == "up":
        results = guest.run_checks(inst, lab, Phase.PRE_REBOOT.value, learner)
    elif outcome == "maintenance":
        time.sleep(5)  # let the console settle on its prompt
        results = guest.run_checks_serial(
            inst, lab, Phase.PRE_REBOOT.value, learner, debug_shell=debug_shell
        )
    else:
        res.fail("after the break boot the machine reached neither SSH nor a maintenance prompt")
        res.fail("console tail:\n" + inst.serial_tail(1500))
        return
    by_id = {r["id"]: r for r in results}
    for c in m.checks:
        r = by_id.get(c.id)
        if r is None:
            res.fail(f"{c.id}: produced no result after the break boot")
        elif (
            r["passed"]
            and not c.baseline_pass
            and not (c.maintenance_pass and outcome == "maintenance")
        ):
            res.fail(
                f"{c.id}: PASSES after the boot that follows the break — the fault does not "
                f"survive that boot, so the learner never meets it ({r['message']})"
            )
    step("every check still fails after that boot" if not res.failures else "after the break boot")
