"""Doctor — can this host run labs, and if not, exactly what to do. The TUI runs it on start."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from norboten import containers, host, hostsetup
from norboten.images import store
from norboten.lima import install
from norboten.lima.instance import Instance
from norboten.models import format_size

OK, WARN, FAIL = "ok", "warn", "fail"

_MIN_QEMU = (8, 2, 0)


@dataclass
class Finding:
    name: str
    status: str
    detail: str
    fix: str = ""
    command: str = ""  # a shell command that fixes it; the setup screen offers to run it


def run() -> list[Finding]:
    findings: list[Finding] = []
    osname = host.host_os()

    if osname == "windows":
        findings.append(
            Finding(
                "platform",
                FAIL,
                "Windows cannot run local labs in v1 (no QEMU snapshots or serial console "
                "under Lima's WSL2 driver)",
                "use hosted mode, or run norboten inside a Linux VM with KVM",
            )
        )
        return findings
    try:
        arch = host.host_arch()
        findings.append(Finding("platform", OK, f"{osname} on {arch.value}"))
    except RuntimeError as e:
        findings.append(Finding("platform", FAIL, str(e)))
        return findings

    accel = host.accelerator()
    if accel:
        findings.append(Finding("virtualization", OK, f"hardware acceleration ({accel})"))
    elif osname == "linux":
        detail, fix, command = hostsetup.kvm_problem() or ("no hardware acceleration", "", "")
        findings.append(Finding("virtualization", FAIL, detail, fix, command))
    else:
        fix = "this Mac does not report Hypervisor.framework support"
        findings.append(Finding("virtualization", FAIL, "no hardware acceleration", fix))

    qemu = host.find_qemu()
    if qemu is None or qemu.version < _MIN_QEMU:
        detail = (
            "QEMU is not installed"
            if qemu is None
            else f"QEMU {qemu.version_str} is too old (need ≥ 8.2)"
        )
        command = hostsetup.qemu_install_command(osname, arch) or ""
        fix = command or (
            f"install {host.qemu_binary_name(arch)} and qemu-img with your package manager"
        )
        hint = hostsetup.rhel_qemu_hint(arch) if qemu is None else None
        if hint:  # installed, but where RHEL puts it
            fix, command = hint, ""
        findings.append(Finding("qemu", FAIL, detail, fix, command))
    else:
        findings.append(Finding("qemu", OK, f"QEMU {qemu.version_str} ({qemu.system})"))

    if install.is_installed():
        findings.append(Finding("lima", OK, f"Lima {install.LIMA_VERSION} (pinned, private copy)"))
    else:
        findings.append(
            Finding(
                "lima",
                OK,
                f"Lima {install.LIMA_VERSION} downloads when a lab first starts (~35 MB)",
            )
        )

    if shutil.which("ssh") is None:
        findings.append(Finding("ssh", FAIL, "no ssh client in PATH", "install OpenSSH"))
    else:
        findings.append(Finding("ssh", OK, "OpenSSH client"))

    if Instance("norboten-rhcsa-05").path_too_long():
        findings.append(
            Finding(
                "paths",
                FAIL,
                f"{install.lima_home()} is too long for UNIX socket paths",
                "export NORBOTEN_HOME=/tmp/norboten (or any short path)",
            )
        )

    mem = host.total_memory_bytes()
    if mem is not None:
        status = OK if mem >= 8 * 1024**3 else WARN
        detail = f"{format_size(mem)} RAM"
        fix = "" if status == OK else "RHCSA labs need ~2 GiB free; prefer the Linux track"
        findings.append(Finding("memory", status, detail, fix))

    free = shutil.disk_usage(store.images_dir().parent if store.images_dir().exists() else "/")
    status = OK if free.free >= 10 * 1024**3 else WARN
    findings.append(
        Finding(
            "disk",
            status,
            f"{format_size(free.free)} free",
            "" if status == OK else "a Rocky lab needs ~5 GiB",
        )
    )

    # optional: only the container labs need it, so its absence is a warning, never a failure
    rt = containers.runtime()
    if rt:
        findings.append(Finding("containers", OK, f"{Path(rt).name} (for the container labs)"))
    else:
        findings.append(
            Finding(
                "containers",
                WARN,
                "no Docker or Podman running",
                "only the container labs need one; install Docker or Podman to run them",
            )
        )

    v3 = host.x86_64_v3()
    if v3 is False:
        findings.append(
            Finding(
                "rocky-10",
                WARN,
                "this CPU lacks x86-64-v3, which Rocky Linux 10 requires",
                "RHCSA labs will not boot here; the Linux track (Ubuntu, Alpine) works",
            )
        )
    return findings


def ready(findings: list[Finding]) -> bool:
    return all(f.status != FAIL for f in findings)
