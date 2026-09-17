"""Container labs: the same machine interface as a Lima instance, backed by Docker or Podman.

A `runtime: container` lab (docs/lab-spec.md §2) has no kernel of its own, no boot and no init
system, so it needs no VM: its base image is built on the learner's machine from a Dockerfile in
the content (images/registry.yaml, `kind: container`) and the lab runs in one long-lived container.
Everything the engine and the grader do goes through `run`, as it does over SSH for a VM: a string
is handed to the container's shell, `sudo` means root, and the learner is the image's `learner`.

The clean snapshot is `docker commit` of the container right after it was created, before the
faults; a reset recreates the container from that image. A container cannot reboot, which is why a
container lab may not be `reboot_required` (models.LabManifest).
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from norboten.lima.instance import Result
from norboten.models import BaseImage
from norboten.paths import content_root, repo_root

LEARNER = "learner"
LABEL = "org.norboten.lab"


class ContainerError(RuntimeError):
    pass


_found: str | None = None


def runtime() -> str | None:
    """`docker` or `podman`, whichever answers; NORBOTEN_CONTAINER_RUNTIME picks one. A runtime
    that answered once is remembered for the process; one that did not is asked again next time,
    because Docker Desktop may have been started since."""
    global _found
    if _found:
        return _found
    wanted = os.environ.get("NORBOTEN_CONTAINER_RUNTIME")
    for name in [wanted] if wanted else ["docker", "podman"]:
        path = shutil.which(name)
        if path is None:
            continue
        try:
            ok = subprocess.run(
                [path, "info", "--format", "{{.ID}}"], capture_output=True, timeout=10
            )
        except subprocess.TimeoutExpired:  # Docker Desktop stopped: `docker info` hangs
            continue
        if ok.returncode == 0:
            _found = path
            return path
    return None


def _cli(*args: str, timeout: float | None = 120, input: bytes | None = None) -> Result:
    rt = runtime()
    if rt is None:
        raise ContainerError(
            "this lab runs in a container, and neither Docker nor Podman is running — "
            "see System (8) in the TUI"
        )
    try:
        p = subprocess.run([rt, *args], capture_output=True, timeout=timeout, input=input)
    except subprocess.TimeoutExpired:
        return Result(124, "", f"timed out after {timeout}s")
    return Result(
        p.returncode, p.stdout.decode(errors="replace"), p.stderr.decode(errors="replace")
    )


def dockerfile(image: BaseImage) -> Path:
    assert image.container is not None
    root = content_root() or repo_root()
    if root is None:
        raise ContainerError("no content directory to build the container image from")
    return root / "images" / image.container.dockerfile


def image_present(image: BaseImage) -> bool:
    assert image.container is not None
    return _cli("image", "inspect", image.container.tag, timeout=30).ok


def build(image: BaseImage, *, force: bool = False) -> None:
    """Build the base image from its Dockerfile, with the Dockerfile's directory as the context."""
    assert image.container is not None
    if image_present(image) and not force:
        return
    path = dockerfile(image)
    r = _cli("build", "-t", image.container.tag, "-f", str(path), str(path.parent), timeout=1800)
    if not r.ok:
        raise ContainerError(f"building {image.container.tag} failed:\n{r.err.strip()[-1500:]}")


class Container:
    """One lab's container. Named like the VM it stands in for."""

    admin_user = None  # grading runs as root through `exec`, which a lab cannot take away

    def __init__(self, name: str):
        self.name = name

    @property
    def snapshot_tag(self) -> str:
        return f"norboten-snapshot/{self.name}:clean"

    # -- state --------------------------------------------------------------------------------

    def status(self) -> str | None:
        """'Running' or 'Stopped' — or None if the container does not exist."""
        r = _cli("container", "inspect", "--format", "{{.State.Running}}", self.name, timeout=30)
        if not r.ok:
            return None
        return "Running" if r.out.strip() == "true" else "Stopped"

    def exists(self) -> bool:
        return self.status() is not None

    def is_running(self) -> bool:
        return self.status() == "Running"

    # -- lifecycle ----------------------------------------------------------------------------

    def create(self, image_tag: str, *, memory_bytes: int, cpus: int) -> None:
        memory = f"{memory_bytes // (1024 * 1024)}m"
        r = _cli(
            "create", "--name", self.name, "--hostname", self.name,
            "--label", f"{LABEL}={self.name}", "--memory", memory, "--cpus", str(cpus), image_tag,
        )  # fmt: skip
        if not r.ok:
            raise ContainerError(f"creating {self.name} failed: {r.err.strip()}")

    def start(self, timeout_s: int = 60, fast: bool = False) -> None:
        r = _cli("start", self.name, timeout=timeout_s)
        if not r.ok:
            raise ContainerError(f"starting {self.name} failed: {r.err.strip()}")

    def stop(self, force: bool = False) -> None:
        if self.is_running():
            _cli("stop", "--time", "0" if force else "3", self.name, timeout=60)

    def delete(self) -> None:
        if self.exists():
            _cli("rm", "--force", self.name, timeout=60)
        _cli("image", "rm", "--force", self.snapshot_tag, timeout=60)

    def snapshot(self) -> None:
        """The clean state, before any fault: the container's filesystem as an image."""
        r = _cli("commit", self.name, self.snapshot_tag, timeout=300)
        if not r.ok:
            raise ContainerError(f"snapshotting {self.name} failed: {r.err.strip()}")

    def restore(self) -> None:
        """Back to the clean snapshot: a new container from it, under the same name."""
        info = _cli(
            "container", "inspect", "--format", "{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}",
            self.name, timeout=30,
        )  # fmt: skip
        memory, nano = (int(x) for x in info.out.split()) if info.ok else (256 * 1024**2, 10**9)
        _cli("rm", "--force", self.name, timeout=60)
        self.create(self.snapshot_tag, memory_bytes=memory, cpus=max(1, nano // 10**9))
        self.start()

    # -- access -------------------------------------------------------------------------------

    def exec_argv(self, *, tty: bool = False, user: str = LEARNER) -> list[str]:
        rt = runtime()
        if rt is None:
            raise ContainerError("neither Docker nor Podman is running")
        flags = ["-it"] if tty else ["-i"]
        return [rt, "exec", *flags, "-u", user, "-w", _home(user), self.name]

    def ssh_argv(
        self, *, master: bool = True, tty: bool = False, user: str | None = None
    ) -> list[str]:
        """What the recorder and the shell command spawn: a login shell in the container."""
        return [*self.exec_argv(tty=tty, user=user or LEARNER), "bash", "-l"]

    def run(
        self,
        command: str | list[str],
        *,
        sudo: bool = False,
        input: bytes | str | None = None,
        timeout: float | None = 120,
        master: bool = True,
        user: str | None = None,
    ) -> Result:
        """Run a command in the container. A string is passed to its shell as-is."""
        remote = command if isinstance(command, str) else shlex.join(command)
        who = "root" if sudo else (user or LEARNER)
        data = input.encode() if isinstance(input, str) else input
        rt = runtime()
        if rt is None:
            raise ContainerError("neither Docker nor Podman is running")
        argv = [rt, "exec", "-i", "-u", who, "-w", _home(who), self.name, "sh", "-c", remote]
        try:
            p = subprocess.run(argv, input=data, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return Result(124, "", f"timed out after {timeout}s")
        return Result(
            p.returncode, p.stdout.decode(errors="replace"), p.stderr.decode(errors="replace")
        )

    def interactive(self, command: str | None = None) -> int:
        argv = self.ssh_argv(tty=True)
        if command:
            argv = [*argv[:-2], "sh", "-c", command]
        return subprocess.call(argv)

    def wait_ssh(self, timeout_s: float = 30) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.is_running() and self.run("true", timeout=10).ok:
                return True
            time.sleep(1)
        return False

    def reboot(self, timeout_s: float = 180) -> bool:
        """A container has no boot to go through; container labs never ask for one."""
        return False

    def serial_tail(self, n_bytes: int = 3000) -> str:
        r = _cli("logs", "--tail", "50", self.name, timeout=30)
        return (r.out + r.err)[-n_bytes:]

    def connect_hint(self) -> str:
        rt = Path(runtime() or "docker").name
        return f"{rt} exec -it -u {LEARNER} {self.name} bash -l"


def _home(user: str) -> str:
    return "/root" if user == "root" else f"/home/{user}"
