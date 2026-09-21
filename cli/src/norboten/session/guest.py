"""Host side of the guest runner: bundle, inject, run, parse.

The runner and the lab scripts travel as one tar.gz over SSH into /run/norboten (tmpfs, root-only,
gone on reboot) and are deleted after each run. Break scripts are never present while the learner
works; check scripts only while a grading pass or the TUI's live panel is running.
"""

from __future__ import annotations

import io
import json
import secrets
import shlex
import tarfile
from collections.abc import Iterator
from pathlib import Path

import norboten_runner
from norboten.labs.manifest import Lab
from norboten.lima.instance import Instance, Result
from norboten.lima.serial_shell import SerialShell

GUEST_DIR = "/run/norboten"
GUEST_LAB = f"{GUEST_DIR}/lab"
GRADER = "norboten-grader"

# Runs once, as the learner (who still has sudo), before the clean snapshot. From then on every
# runner command uses this account, so a lab can take sudo away from the learner (RHCSA Lab 5's
# unknown root password) and a learner who breaks their own sudo does not break grading.
_INSTALL_GRADER = f"""set -e
id {GRADER} >/dev/null 2>&1 || useradd --system --create-home --shell /bin/sh {GRADER}
passwd -l {GRADER} >/dev/null 2>&1 || true
home=$(getent passwd {GRADER} | cut -d: -f6)
install -d -m 700 -o {GRADER} "$home/.ssh"
learner_home=$(getent passwd "$1" | cut -d: -f6)
install -m 600 -o {GRADER} "$learner_home/.ssh/authorized_keys" "$home/.ssh/authorized_keys"
printf '{GRADER} ALL=(ALL) NOPASSWD: ALL\\n' > /etc/sudoers.d/00-{GRADER}
chmod 440 /etc/sudoers.d/00-{GRADER}
"""


class GuestError(RuntimeError):
    pass


def _runner_dir() -> Path:
    return Path(norboten_runner.__file__).parent


def bundle(lab: Lab, parts: tuple[str, ...]) -> bytes:
    """tar.gz with norboten_runner/ and the requested lab subdirectories (plus files/)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for f in sorted(_runner_dir().glob("*.py")):
            tar.add(f, arcname=f"norboten_runner/{f.name}")
        tar.add(lab.path / "lab.yaml", arcname="lab/lab.yaml")
        for part in (*parts, "files"):
            src = lab.path / part
            if src.is_dir():
                tar.add(src, arcname=f"lab/{part}", filter=_no_pycache)
    return buf.getvalue()


def bundle_with_runner(lab_tar_gz: bytes) -> bytes:
    """A bundle the API sent for a rated attempt (entries under lab/), plus this client's runner."""
    buf = io.BytesIO()
    with (
        tarfile.open(fileobj=io.BytesIO(lab_tar_gz), mode="r:gz") as src,
        tarfile.open(fileobj=buf, mode="w:gz") as tar,
    ):
        for f in sorted(_runner_dir().glob("*.py")):
            tar.add(f, arcname=f"norboten_runner/{f.name}")
        for member in src.getmembers():
            name = member.name.lstrip("./")
            if not name.startswith("lab/") or ".." in name.split("/") or member.issym():
                raise GuestError(f"the rated bundle carries an unexpected entry: {member.name}")
            if member.islnk() or not (member.isfile() or member.isdir()):
                continue
            member.name = name
            tar.addfile(member, src.extractfile(member) if member.isfile() else None)
    return buf.getvalue()


def _no_pycache(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    return None if "__pycache__" in info.name else info


def install_grader(inst: Instance, learner: str) -> None:
    r = inst.run(f"sh -s {learner}", sudo=True, input=_INSTALL_GRADER, timeout=60)
    if not r.ok:
        raise GuestError(f"could not create the grader account: {r.err.strip()}")
    if not root(inst, "true").ok:
        raise GuestError("the grader account cannot log in")


def root(inst: Instance, command: str, *, input=None, timeout: float | None = 120) -> Result:
    """A command as root, through the grader account."""
    return inst.run(command, sudo=True, input=input, timeout=timeout, user=GRADER)


def inject(inst: Instance, data: bytes) -> None:
    r = root(
        inst,
        f"umask 077; rm -rf {GUEST_DIR}; mkdir -p {GUEST_DIR}; tar -xzf - -C {GUEST_DIR}",
        input=data,
        timeout=60,
    )
    if not r.ok:
        raise GuestError(f"could not copy the runner into the VM: {r.err.strip()}")


def cleanup(inst: Instance) -> None:
    root(inst, f"rm -rf {GUEST_DIR}", timeout=30)


def python(inst: Instance, module: str, *args: str, timeout: float = 600) -> Result:
    cmd = " ".join([f"PYTHONPATH={GUEST_DIR}", "python3", "-m", module, *args])
    return root(inst, cmd, timeout=timeout)


def json_lines(text: str) -> Iterator[dict]:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                yield json.loads(line)
            except ValueError:
                continue


def apply_faults(inst: Instance, lab: Lab, learner: str) -> list[str]:
    return apply_bundle(inst, bundle(lab, ("break",)), learner)


def apply_bundle(inst: Instance, data: bytes, learner: str) -> list[str]:
    """Apply the faults from a prepared bundle — a rated attempt's, which never touches the disk."""
    inject(inst, data)
    try:
        r = python(inst, "norboten_runner.break_runner", GUEST_LAB, "--learner", learner)
    finally:
        cleanup(inst)
    docs = list(json_lines(r.out))
    if not r.ok or not docs or "applied" not in docs[-1]:
        detail = docs[-1] if docs else {"error": r.err.strip() or r.out.strip()}
        raise GuestError(f"applying the faults failed: {detail}")
    return docs[-1]["applied"]


def _collect_command(phase: str, learner: str, attempt: str, nonce: str) -> str:
    return " ".join(
        [
            f"PYTHONPATH={GUEST_DIR}",
            "python3 -m norboten_runner.collect_runner",
            GUEST_LAB,
            *("--phase", phase, "--learner", shlex.quote(learner)),
            *("--attempt", shlex.quote(attempt), "--nonce", shlex.quote(nonce)),
        ]
    )


def collect(
    inst: Instance, data: bytes, phase: str, learner: str, attempt: str, nonce: str, key: str
) -> dict:
    """Run a rated lab's collectors in the guest: {record, signature} (lab-spec §13). The key goes
    in on stdin, so it is never on a command line in the guest."""
    inject(inst, data)
    try:
        r = root(inst, _collect_command(phase, learner, attempt, nonce), input=key + "\n")
    finally:
        cleanup(inst)
    docs = [d for d in json_lines(r.out) if "record" in d]
    if not docs:
        raise GuestError(
            f"collecting the facts produced nothing: {(r.err or r.out).strip()[-500:]}"
        )
    return docs[-1]


def _judged(lab: Lab, collected: dict) -> list[dict]:
    from norboten_runner.judge import judge_record

    return judge_record(str(lab.path), collected["record"])


def run_checks(inst: Instance, lab: Lab, phase: str, learner: str) -> list[dict]:
    if lab.manifest.rated:
        # a rated lab in an author's checkout: collect in the guest, judge here, as the server does
        key = secrets.token_hex(32)
        data = bundle(lab, ("collect",))
        return _judged(lab, collect(inst, data, phase, learner, "local", "local", key))
    inject(inst, bundle(lab, ("check",)))
    try:
        r = python(
            inst, "norboten_runner.check_runner", GUEST_LAB, "--phase", phase, "--learner", learner
        )
    finally:
        cleanup(inst)
    docs = list(json_lines(r.out))
    if not docs:
        raise GuestError(f"the check runner produced no result: {(r.err or r.out).strip()[-500:]}")
    return docs[-1]["results"]


def run_checks_serial(
    inst: Instance, lab: Lab, phase: str, learner: str, debug_shell: bool = False
) -> list[dict]:
    """The same checks through a root shell on a serial port, for a machine with no network: the
    gate's debug shell on the spare port when it was opened, else sulogin on the console."""
    sock = inst.spare_serial_socket if debug_shell else inst.serial_socket
    rated = lab.manifest.rated
    key = secrets.token_hex(32)
    if rated:
        command = f"echo {key} | " + _collect_command(phase, learner, "local", "local")
    else:
        command = (
            f"PYTHONPATH={GUEST_DIR} python3 -m norboten_runner.check_runner {GUEST_LAB} "
            f"--phase {phase} --learner {learner}"
        )
    with SerialShell(sock, timeout=30) as shell:
        shell.login()
        shell.run(f"rm -rf {GUEST_DIR}; mkdir -p -m 700 {GUEST_DIR}")
        shell.upload(bundle(lab, ("collect" if rated else "check",)), f"{GUEST_DIR}/bundle.tgz")
        shell.run(f"tar -xzf {GUEST_DIR}/bundle.tgz -C {GUEST_DIR}")
        try:
            _, out = shell.run_status(command, timeout=600)
        finally:
            shell.run_status(f"rm -rf {GUEST_DIR}", timeout=30)
    if rated:
        collected = [d for d in json_lines(out) if "record" in d]
        if not collected:
            raise GuestError(f"collecting the facts on the console produced nothing: {out[-500:]}")
        return _judged(lab, collected[-1])
    docs = list(json_lines(out))
    if not docs:
        raise GuestError(
            f"the check runner produced no result on the console: {out.strip()[-500:]}"
        )
    return docs[-1]["results"]


_DEBUG_SHELL = """[Service]
TTYPath={tty}
"""


def open_debug_shell(inst: Instance) -> bool:
    """Put systemd's debug shell on the VM's spare serial port, for the gate only.

    debug-shell.service starts a root shell very early in every boot, emergency mode included, and
    needs no password — so the gate reaches a machine whose root password a lab has changed. Which
    guest tty the spare port is differs by architecture, so it is found by writing a marker to each
    candidate and seeing which one arrives in the port's log. False without systemd or a spare port.
    """
    import time

    if not root(inst, "command -v systemctl >/dev/null && test -d /run/systemd/system").ok:
        return False
    listing = root(inst, "ls /dev/ttyS* /dev/ttyAMA* /dev/hvc* 2>/dev/null").out.split()
    for tty in listing:
        marker = f"NB-SPARE-{tty.rsplit('/', 1)[-1]}"
        root(inst, f"timeout 3 sh -c 'printf \"%s\\n\" {marker} > {tty}' 2>/dev/null", timeout=10)
        time.sleep(0.5)
        try:
            log = inst.spare_serial_log.read_text(errors="replace")
        except OSError:
            return False
        if marker in log:
            dropin = _DEBUG_SHELL.format(tty=tty)
            r = root(
                inst,
                "mkdir -p /etc/systemd/system/debug-shell.service.d && "
                "cat > /etc/systemd/system/debug-shell.service.d/norboten-gate.conf && "
                # a virtio console gets a getty of its own, which would read the same port
                f"systemctl mask serial-getty@{tty.rsplit('/', 1)[-1]}.service && "
                "systemctl daemon-reload && systemctl enable debug-shell.service",
                input=dropin,
                timeout=30,
            )
            return r.ok
    return False


def reboot_into_broken(inst: Instance, timeout_s: float = 150) -> str:
    """Reboot after the break and return 'up', 'maintenance' (emergency or rescue prompt on the
    console) or 'timeout'. Watching the console reports a broken boot as soon as it happens."""
    import time

    before = inst.boot_id()
    offset = inst.serial_size()
    inst.run("(sleep 1; reboot) >/dev/null 2>&1 &", sudo=True, timeout=15, user=GRADER)
    inst.reset_ssh()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        console = inst.serial_since(offset)
        if "Give root password for maintenance" in console or "emergency mode" in console:
            return "maintenance"
        now = inst.run("cat /proc/sys/kernel/random/boot_id", timeout=5, master=False)
        if now.ok and now.out.strip() and now.out.strip() != before:
            return "up"
        time.sleep(2)
    return "timeout"


def facts(inst: Instance, lab: Lab, learner: str) -> dict:
    inject(inst, bundle(lab, ()))
    try:
        r = python(inst, "norboten_runner.facts", "--learner", learner, timeout=60)
    finally:
        cleanup(inst)
    docs = list(json_lines(r.out))
    return docs[-1] if docs else {}


def run_solution(inst: Instance, lab: Lab, image_id: str, learner: str) -> Result:
    script = lab.solution_for(image_id).read_text()
    root(inst, f"umask 077; mkdir -p {GUEST_DIR}; cat > {GUEST_DIR}/solution.sh", input=script)
    try:
        return root(inst, f"NORBOTEN_LEARNER={learner} sh {GUEST_DIR}/solution.sh", timeout=900)
    finally:
        cleanup(inst)
