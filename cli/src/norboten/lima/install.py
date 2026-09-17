"""Download and pin Lima. Norboten never uses a system-wide Lima.

Pinning matters: snapshot and serial-console behaviour differ between Lima releases, and the
solvability gate must run on exactly the Lima the learner gets. Bump LIMA_VERSION and the digests
together, from the release's SHA256SUMS file.
"""

from __future__ import annotations

import hashlib
import platform
import shutil
import tarfile
import tempfile
from pathlib import Path

import httpx

from norboten.paths import norboten_home

LIMA_VERSION = "2.2.0"
_BASE = f"https://github.com/lima-vm/lima/releases/download/v{LIMA_VERSION}"
_DIGESTS = {
    ("Darwin", "arm64"): "bbdef91774885a0d05f7b048c4eb89ae2bcf3a0c252ae7ca7934e63df76d93c3",
    ("Darwin", "x86_64"): "0d6f99c19f6e4bc3c92730c4c29d929e6927f0cb0a0ba1a84383367135a8ff31",
    ("Linux", "aarch64"): "7c6a09c6844f55f811e9b7b2b60a6070a512c696c8ec752dfdb3c8ed50ed0364",
    ("Linux", "x86_64"): "a0ea1ccf6b7335a900adb5f8d2b8384457965fecb1ba72f09b4e3e46d12f424a",
}


class LimaUnavailable(RuntimeError):
    pass


def host_key() -> tuple[str, str]:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Linux" and machine == "arm64":
        machine = "aarch64"
    if system == "Darwin" and machine == "aarch64":
        machine = "arm64"
    if machine == "amd64":
        machine = "x86_64"
    return system, machine


def lima_dir() -> Path:
    return norboten_home() / "lima" / LIMA_VERSION


def limactl_path() -> Path:
    return lima_dir() / "bin" / "limactl"


def lima_home() -> Path:
    """LIMA_HOME for Norboten's instances — kept apart from any Lima the user runs themselves."""
    return norboten_home() / "vms"


def is_installed() -> bool:
    return limactl_path().is_file()


def install(progress=None) -> Path:
    """Download, verify and unpack the pinned Lima. Returns the limactl path."""
    if is_installed():
        return limactl_path()
    key = host_key()
    if key not in _DIGESTS:
        raise LimaUnavailable(
            f"no pinned Lima build for {key[0]}/{key[1]}; local labs need macOS or Linux"
        )
    system, machine = key
    url = f"{_BASE}/lima-{LIMA_VERSION}-{system}-{machine}.tar.gz"
    target = lima_dir()
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
        archive = Path(tmp) / "lima.tar.gz"
        sha = hashlib.sha256()
        with httpx.stream("GET", url, follow_redirects=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0))
            with archive.open("wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
                    sha.update(chunk)
                    if progress:
                        progress(len(chunk), total)
        if sha.hexdigest() != _DIGESTS[key]:
            raise LimaUnavailable(f"Lima download from {url} failed its checksum — not installed")
        unpacked = Path(tmp) / "lima"
        with tarfile.open(archive) as tar:
            tar.extractall(unpacked, filter="data")
        if target.exists():
            shutil.rmtree(target)
        unpacked.rename(target)
    return limactl_path()
