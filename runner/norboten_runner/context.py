"""The `ctx` object handed to every break and check script. Standard library only."""

from __future__ import annotations

import json
import os
import pwd
import shlex
import subprocess
from dataclasses import dataclass

from norboten_runner.report import make_result

STATE_DIR = "/var/lib/norboten"
STATE_FILE = os.path.join(STATE_DIR, "state.json")
BASE_FILE = "/etc/norboten/base.json"


class CommandFailed(RuntimeError):
    pass


@dataclass
class Run:
    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.code == 0

    @property
    def text(self) -> str:
        """stdout and stderr together, for evidence."""
        return (self.out + ("\n" + self.err if self.err else "")).strip()


def load_facts() -> dict:
    try:
        with open(BASE_FILE) as f:
            return json.load(f)
    except OSError:
        return {"id": "unknown", "init": "systemd", "pkg": "unknown", "mac": "none"}


class Context:
    def __init__(self, lab_dir: str, *, phase: str, learner: str, state_file: str | None = None):
        self.lab_dir = lab_dir
        self.phase = phase
        self.learner = learner
        self.facts = load_facts()
        self._state_file = state_file or STATE_FILE
        self.state = self._load_state()
        self.check_id = ""

    # -- state shared between break and check --------------------------------------------------

    def _load_state(self) -> dict:
        try:
            with open(self._state_file) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def save_state(self) -> None:
        os.makedirs(os.path.dirname(self._state_file), mode=0o700, exist_ok=True)
        tmp = self._state_file + ".tmp"
        with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
            json.dump(self.state, f)
        os.replace(tmp, self._state_file)

    # -- system access -----------------------------------------------------------------------

    def run(
        self,
        cmd,
        *,
        check: bool = False,
        timeout: float = 30,
        input: str | None = None,
        user: str | None = None,
        env: dict | None = None,
    ) -> Run:
        """Run a command. A string goes through /bin/sh; a list is executed directly."""
        if user:
            inner = cmd if isinstance(cmd, str) else " ".join(shlex.quote(a) for a in cmd)
            cmd = ["su", "-s", "/bin/sh", "-c", inner, user]
        merged = {**os.environ, "LC_ALL": "C", **(env or {})}
        try:
            p = subprocess.run(
                cmd,
                shell=isinstance(cmd, str),
                capture_output=True,
                text=True,
                timeout=timeout,
                input=input,
                env=merged,
            )
            result = Run(p.returncode, p.stdout, p.stderr)
        except subprocess.TimeoutExpired:
            result = Run(124, "", f"timed out after {timeout}s")
        except FileNotFoundError as e:
            result = Run(127, "", str(e))
        if check and not result.ok:
            raise CommandFailed(f"{cmd!r} exited {result.code}: {result.text[-500:]}")
        return result

    def read(self, path: str) -> str | None:
        try:
            with open(path, errors="replace") as f:
                return f.read()
        except OSError:
            return None

    def write(
        self,
        path: str,
        content: str,
        *,
        mode: int | None = None,
        owner: str | None = None,
        group: str | None = None,
    ) -> None:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        if mode is not None:
            os.chmod(path, mode)
        if owner or group:
            import grp

            uid = pwd.getpwnam(owner).pw_uid if owner else -1
            gid = grp.getgrnam(group).gr_gid if group else -1
            os.chown(path, uid, gid)

    def learner_home(self) -> str:
        return pwd.getpwnam(self.learner).pw_dir

    # -- init-system neutral service queries -------------------------------------------------

    @property
    def systemd(self) -> bool:
        return self.facts.get("init") == "systemd"

    def service_active(self, name: str) -> bool:
        if self.systemd:
            return self.run(["systemctl", "is-active", "--quiet", name]).ok
        return self.run(["rc-service", name, "status"]).ok

    def service_enabled(self, name: str) -> bool:
        if self.systemd:
            return self.run(["systemctl", "is-enabled", "--quiet", name]).ok
        out = self.run(["rc-update", "show", "default"]).out
        return any(line.split("|")[0].strip() == name for line in out.splitlines())

    # -- results -----------------------------------------------------------------------------

    def passed(self, message: str, evidence: str = "") -> dict:
        return make_result(self.check_id, True, message, evidence)

    def failed(self, message: str, evidence: str = "") -> dict:
        return make_result(self.check_id, False, message, evidence)
