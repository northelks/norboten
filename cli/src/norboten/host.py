"""Facts about the host machine: OS, CPU, QEMU, acceleration."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from norboten.models import Arch


@dataclass(frozen=True)
class QemuInfo:
    system: Path
    img: Path
    version: tuple[int, int, int]

    @property
    def version_str(self) -> str:
        return ".".join(map(str, self.version))


def host_arch() -> Arch:
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return Arch.AARCH64
    if machine in ("x86_64", "amd64"):
        return Arch.X86_64
    raise RuntimeError(f"unsupported CPU architecture {machine!r}")


def host_os() -> str:
    """'macos', 'linux' or 'windows'."""
    return {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}.get(
        platform.system(), platform.system().lower()
    )


def qemu_binary_name(arch: Arch | None = None) -> str:
    return f"qemu-system-{(arch or host_arch()).value}"


def find_qemu() -> QemuInfo | None:
    system = os.environ.get(f"QEMU_SYSTEM_{host_arch().value.upper()}") or shutil.which(
        qemu_binary_name()
    )
    img = shutil.which("qemu-img")
    if not system or not img:
        return None
    try:
        out = subprocess.run([system, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"version (\d+)\.(\d+)\.(\d+)", out.stdout)
    if not m:
        return None
    return QemuInfo(Path(system), Path(img), tuple(int(x) for x in m.groups()))  # type: ignore[arg-type]


def accelerator() -> str | None:
    """'hvf', 'kvm' or None (software emulation only — far too slow for labs)."""
    osname = host_os()
    if osname == "macos":
        try:
            out = subprocess.run(
                ["sysctl", "-n", "kern.hv_support"], capture_output=True, text=True, timeout=5
            )
            return "hvf" if out.stdout.strip() == "1" else None
        except OSError:
            return None
    if osname == "linux":
        return "kvm" if os.access("/dev/kvm", os.R_OK | os.W_OK) else None
    return None


def total_memory_bytes() -> int | None:
    try:
        if host_os() == "macos":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True)
            return int(out.stdout.strip())
        if host_os() == "linux":
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        return None
    return None


def x86_64_v3() -> bool | None:
    """Rocky 10 requires x86-64-v3 (AVX2, BMI2, FMA, MOVBE…). None when not applicable."""
    if host_arch() is not Arch.X86_64:
        return None
    flags = ""
    if host_os() == "linux":
        try:
            flags = Path("/proc/cpuinfo").read_text().lower()
        except OSError:
            return None
        needed = ("avx2", "bmi2", "fma", "movbe")
        return all(re.search(rf"\b{f}\b", flags) for f in needed)
    if host_os() == "macos":
        out = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.leaf7_features", "machdep.cpu.features"],
            capture_output=True,
            text=True,
        )
        flags = out.stdout.lower()
        return all(f in flags for f in ("avx2", "bmi2", "fma", "movbe"))
    return None
