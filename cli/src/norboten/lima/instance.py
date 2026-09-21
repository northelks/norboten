"""Lab VM lifecycle on top of the pinned limactl.

Norboten keeps its VMs in their own LIMA_HOME and always uses the QEMU driver: disk snapshots and
the serial console depend on it (docs/open-questions.md Q2). Guest commands go over the SSH config
Lima writes for each instance; that path is faster than `limactl shell` and lets us stream stdin.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from norboten.host import host_arch
from norboten.lima import install
from norboten.models import Arch

# macOS limits a UNIX socket path to 104 bytes, Linux to 108. Lima appends a 16-char suffix to
# ssh.sock while starting, so check the longest path it will create.
_UNIX_PATH_MAX = 104
_SSH_OPTS = [
    "-o",
    "ConnectTimeout=5",
    "-o",
    "ServerAliveInterval=5",
    "-o",
    "ServerAliveCountMax=3",
    "-o",
    "LogLevel=ERROR",
]


class LimaError(RuntimeError):
    pass


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.code == 0


def _env() -> dict[str, str]:
    return {**os.environ, "LIMA_HOME": str(install.lima_home())}


def limactl(*args: str, timeout: float | None = None, check: bool = True) -> Result:
    cmd = [str(install.limactl_path()), *args]
    try:
        p = subprocess.run(cmd, env=_env(), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise LimaError(f"limactl {' '.join(args)} timed out after {timeout}s") from e
    result = Result(p.returncode, p.stdout, p.stderr)
    if check and not result.ok:
        tail = "\n".join(p.stderr.strip().splitlines()[-5:])
        raise LimaError(f"limactl {' '.join(args)} failed:\n{tail}")
    return result


def list_instances() -> dict[str, dict]:
    if not install.is_installed():
        return {}
    r = limactl("list", "--json", check=False)
    out = {}
    for line in r.out.splitlines():
        if line.strip():
            info = json.loads(line)
            out[info["name"]] = info
    return out


class Instance:
    def __init__(self, name: str, admin_user: str | None = None):
        self.name = name
        # The account privileged operations (reboot) go through; None means the Lima user.
        self.admin_user = admin_user

    # -- paths ------------------------------------------------------------------------------

    @property
    def dir(self) -> Path:
        return install.lima_home() / self.name

    @property
    def ssh_config(self) -> Path:
        return self.dir / "ssh.config"

    @property
    def ssh_host(self) -> str:
        """The Host alias in ssh.config. Lima writes dots as dashes, so an instance built from
        an image id like `ubuntu-26.04` answers to `lima-lb-ubuntu-26-04`, not to its own name."""
        return f"lima-{self.name.replace('.', '-')}"

    @property
    def serial_socket(self) -> Path:
        """The guest's primary serial port: kernel console and login prompt."""
        return self.dir / "serial.sock"

    @property
    def serial_log(self) -> Path:
        return self.dir / "serial.log"

    @property
    def spare_serial_socket(self) -> Path:
        """A serial port the guest does not use; the gate puts a debug shell on it. Lima gives
        aarch64 a PCI serial port, and x86_64 none (pkg/driver/qemu/qemu.go, "ARM only"); there
        the virtio console is the spare one, since the kernel console is ttyS0."""
        return self.dir / f"{self._spare_serial}.sock"

    @property
    def spare_serial_log(self) -> Path:
        return self.dir / f"{self._spare_serial}.log"

    @property
    def _spare_serial(self) -> str:
        return "serialp" if host_arch() is Arch.AARCH64 else "serialv"

    @property
    def boot_console_socket(self) -> Path:
        """Where UEFI/GRUB draw their menu. On aarch64 that is the virtio console."""
        return self.dir / "serialv.sock"

    def disk_name(self, index: int) -> str:
        return f"{self.name}-d{index}"

    def disk_paths(self) -> list[Path]:
        disks = [self.dir / "disk"]
        i = 1
        while (install.lima_home() / "_disks" / self.disk_name(i) / "datadisk").exists():
            disks.append(install.lima_home() / "_disks" / self.disk_name(i) / "datadisk")
            i += 1
        return disks

    def path_too_long(self) -> bool:
        return len(str(self.dir / "ssh.sock.1234567890123456").encode()) >= _UNIX_PATH_MAX

    # -- state ------------------------------------------------------------------------------

    def status(self) -> str | None:
        """'Running', 'Stopped', 'Broken' — or None if the instance does not exist."""
        info = list_instances().get(self.name)
        return info["status"] if info else None

    def exists(self) -> bool:
        return self.status() is not None

    def is_running(self) -> bool:
        return self.status() == "Running"

    # -- lifecycle --------------------------------------------------------------------------

    def create(self, config: dict, extra_disks: Sequence[str] = ()) -> None:
        if self.path_too_long():
            raise LimaError(
                f"{self.dir} is too long for a UNIX socket path; set NORBOTEN_HOME to a shorter "
                "directory (for example /tmp/norboten)"
            )
        for i, size in enumerate(extra_disks, start=1):
            limactl("disk", "create", self.disk_name(i), "--size", size, "--format", "qcow2")
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            yaml.safe_dump(config, f, sort_keys=False)
            path = f.name
        try:
            limactl("create", "--tty=false", "--name", self.name, path)
        finally:
            os.unlink(path)

    def start(self, timeout_s: int = 600, fast: bool = False) -> None:
        """Boot the VM. fast=True returns as soon as the guest answers SSH.

        `limactl start` makes one SSH attempt as soon as QEMU starts; slirp then retransmits
        its SYN with exponential backoff while the guest boots, so Lima reports ready ~10-15 s
        after the guest actually is. For a VM that has booted before (reset, reboot, resume),
        poll with fresh short connections instead and let limactl finish in the background.
        """
        if not fast:
            limactl(
                "start",
                "--tty=false",
                f"--timeout={timeout_s}s",
                self.name,
                timeout=timeout_s + 30,
            )
            self.reset_ssh()
            return
        before = self.ssh_config.stat().st_mtime if self.ssh_config.exists() else 0
        log = (self.dir / "norboten-start.log").open("w")
        proc = subprocess.Popen(
            [
                str(install.limactl_path()),
                "start",
                "--tty=false",
                f"--timeout={timeout_s}s",
                self.name,
            ],
            env=_env(),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self._pending = proc
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            code = proc.poll()
            if code is not None:
                if code != 0:
                    tail = (self.dir / "norboten-start.log").read_text()[-600:]
                    raise LimaError(f"limactl start {self.name} failed:\n{tail}")
                self._pending = None
                self.reset_ssh()
                return
            fresh = self.ssh_config.exists() and self.ssh_config.stat().st_mtime > before
            if fresh and self.run("test -e /run/lima-boot-done", timeout=4).ok:
                return
            time.sleep(0.5)
        raise LimaError(f"{self.name} did not boot within {timeout_s}s")

    def _master_ready(self) -> bool:
        """While a background `limactl start` is still settling, bypass the ControlMaster so we
        never race the host agent into creating it."""
        pending = getattr(self, "_pending", None)
        return pending is None or pending.poll() is not None

    def stop(self, force: bool = False) -> None:
        if self.status() != "Running":
            return
        self.reset_ssh()
        args = ["stop", self.name] + (["--force"] if force else [])
        limactl(*args, timeout=180)

    def delete(self) -> None:
        if self.exists():
            self.reset_ssh()
            limactl("delete", "--force", self.name, timeout=120)
        i = 1
        while (install.lima_home() / "_disks" / self.disk_name(i)).exists():
            limactl("disk", "delete", "--force", self.disk_name(i), check=False)
            i += 1

    # -- guest access -----------------------------------------------------------------------

    def reset_ssh(self) -> None:
        """Drop the SSH ControlMasters. After a disk rollback or guest reboot they point at a TCP
        connection the guest no longer knows about, and every command through them would hang."""
        for sock in self.dir.glob("*.sock"):
            if sock.name not in ("ssh.sock",) and not sock.name.endswith(("-grader.sock",)):
                continue
            subprocess.run(
                ["ssh", "-O", "exit", "-S", str(sock), self.ssh_host],
                capture_output=True,
                timeout=10,
                check=False,
            )

    def ssh_argv(
        self, *, master: bool = True, tty: bool = False, user: str | None = None
    ) -> list[str]:
        argv = ["ssh", "-F", str(self.ssh_config), *_SSH_OPTS]
        if user:
            # a different account needs its own ControlMaster socket
            argv += ["-o", f"User={user}", "-o", f"ControlPath={self.dir / (user + '.sock')}"]
        if not master:
            argv += ["-o", "ControlMaster=no", "-o", "ControlPath=none"]
        if tty:
            argv.append("-t")
        return [*argv, self.ssh_host]

    def run(
        self,
        command: str | Sequence[str],
        *,
        sudo: bool = False,
        input: bytes | str | None = None,
        timeout: float | None = 120,
        master: bool = True,
        user: str | None = None,
    ) -> Result:
        """Run a command in the guest. A string is passed to the guest shell as-is."""
        remote = command if isinstance(command, str) else " ".join(_quote(a) for a in command)
        if sudo:
            remote = f"sudo -n sh -c {_quote(remote)}"
        data = input.encode() if isinstance(input, str) else input
        master = master and self._master_ready()
        try:
            p = subprocess.run(
                [*self.ssh_argv(master=master, user=user), remote],
                input=data,
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return Result(124, "", f"timed out after {timeout}s")
        return Result(
            p.returncode, p.stdout.decode(errors="replace"), p.stderr.decode(errors="replace")
        )

    def interactive(self, command: str | None = None) -> int:
        """Attach the user's terminal: a login shell, or one command with a TTY."""
        argv = self.ssh_argv(tty=True, master=self._master_ready())
        if command:
            argv.append(command)
        return subprocess.call(argv)

    def boot_id(self) -> str | None:
        r = self.run("cat /proc/sys/kernel/random/boot_id", timeout=10, master=False)
        return r.out.strip() if r.ok else None

    def wait_ssh(self, timeout_s: float = 180) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.run("true", timeout=10, master=False).ok:
                return True
            time.sleep(2)
        return False

    def reboot(self, timeout_s: float = 180) -> bool:
        """Reboot from inside the guest and wait for a new boot id. False if it never came back."""
        before = self.boot_id()
        self.run("(sleep 1; reboot) >/dev/null 2>&1 &", sudo=True, timeout=15, user=self.admin_user)
        self.reset_ssh()
        time.sleep(3)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            now = self.boot_id()
            if now and now != before:
                return True
            time.sleep(2)
        return False

    def serial_size(self) -> int:
        try:
            return self.serial_log.stat().st_size
        except OSError:
            return 0

    def serial_since(self, offset: int) -> str:
        try:
            with self.serial_log.open("rb") as f:
                f.seek(offset)
                return f.read().decode(errors="replace")
        except OSError:
            return ""

    def serial_tail(self, n_bytes: int = 3000) -> str:
        try:
            data = self.serial_log.read_bytes()[-n_bytes:]
        except OSError:
            return ""
        text = data.decode(errors="replace")
        return "".join(ch for ch in text if ch.isprintable() or ch in "\n\t")


def _quote(s: str) -> str:
    import shlex

    return shlex.quote(s)
