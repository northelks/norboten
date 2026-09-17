"""The commands that prepare a host for labs: QEMU from the system's package manager, and access
to /dev/kvm. Doctor prints them; the setup screen runs them, after asking.
"""

from __future__ import annotations

import getpass
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from norboten.models import Arch

OS_RELEASE = Path("/etc/os-release")
KVM = Path("/dev/kvm")
RHEL_QEMU = Path("/usr/libexec/qemu-kvm")


def os_release(path: Path = OS_RELEASE) -> tuple[str, str]:
    """(ID, ID_LIKE) from os-release, lower-case; empty strings where it says nothing."""
    fields = {}
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return "", ""
    for line in lines:
        key, sep, value = line.partition("=")
        if sep:
            fields[key.strip()] = value.strip().strip("\"'").lower()
    return fields.get("ID", ""), fields.get("ID_LIKE", "")


def qemu_install_command(
    osname: str,
    arch: Arch,
    *,
    release: Path = OS_RELEASE,
    which: Callable[[str], str | None] | None = None,
    root: bool | None = None,
) -> str | None:
    """The package-manager command that installs QEMU here, or None if this system is unknown."""
    which = which or shutil.which
    if osname == "macos":
        if which("brew"):
            return "brew install qemu"
        if which("port"):
            return "sudo port install qemu"
        return None
    if osname != "linux":
        return None
    ident, like = os_release(release)
    family = {ident, *like.split()}
    x86 = arch == Arch.X86_64
    if family & {"debian", "ubuntu"}:
        pkg = "qemu-system-x86" if x86 else "qemu-system-arm"
        cmd = (
            "sudo apt-get update && "
            f"sudo apt-get install -y --no-install-recommends {pkg} qemu-utils"
        )
    elif ident == "fedora":
        pkg = "qemu-system-x86-core" if x86 else "qemu-system-aarch64-core"
        cmd = f"sudo dnf install -y {pkg} qemu-img"
    elif family & {"rhel", "centos", "rocky", "almalinux"}:
        cmd = "sudo dnf install -y qemu-kvm qemu-img"
    elif "arch" in family:
        cmd = "sudo pacman -S --needed --noconfirm qemu-base"
    elif family & {"suse", "opensuse"} or ident.startswith("opensuse"):
        cmd = f"sudo zypper install -y qemu-tools qemu-{'x86' if x86 else 'arm'}"
    elif "alpine" in family:
        cmd = f"sudo apk add qemu-system-{arch.value} qemu-img"
    else:
        return None
    if root if root is not None else os.geteuid() == 0:
        cmd = cmd.replace("sudo ", "")
    return cmd


def rhel_qemu_hint(arch: Arch, binary: Path = RHEL_QEMU) -> str | None:
    """RHEL and its rebuilds ship QEMU as /usr/libexec/qemu-kvm, off PATH: how to point at it."""
    if binary.is_file():
        return f"export QEMU_SYSTEM_{arch.value.upper()}={binary}"
    return None


def kvm_problem(device: Path = KVM) -> tuple[str, str, str] | None:
    """(what is wrong, how to fix it, the command that does) for /dev/kvm on Linux; None if usable.

    The command is empty where only the firmware or the hypervisor underneath can help.
    """
    if not device.exists():
        return (
            f"{device} does not exist",
            "enable virtualization in the BIOS/UEFI, or nested virtualization in the VM this "
            "runs in",
            "",
        )
    if os.access(device, os.R_OK | os.W_OK):
        return None
    user = getpass.getuser()
    command = f"sudo usermod -aG kvm {user}"
    return (
        f"{device} is not usable by {user}",
        f"{command}, then log out and back in",
        command,
    )
