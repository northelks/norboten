"""The TUI's live check panel: checks re-run every few seconds, streamed over one SSH session.

The check scripts stay in the guest's /run/norboten while the panel is open (docs/lab-spec.md §5)
and are removed when it closes.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import threading
from collections.abc import Callable

from norboten.labs.manifest import Lab
from norboten.lima.instance import Instance
from norboten.models import PassResult, Phase
from norboten.session import guest


class LiveChecks:
    def __init__(self, inst: Instance, lab: Lab, learner: str, interval: float = 2.0):
        self.inst, self.lab, self.learner, self.interval = inst, lab, learner, interval
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None

    def start(self, on_pass: Callable[[PassResult], None], on_error: Callable[[str], None]) -> None:
        guest.inject(self.inst, guest.bundle(self.lab, ("check",)))
        remote = (
            f"PYTHONPATH={guest.GUEST_DIR} python3 -m norboten_runner.check_runner "
            f"{guest.GUEST_LAB} --phase live --learner {shlex.quote(self.learner)} "
            f"--watch {self.interval}"
        )
        argv = [*self.inst.ssh_argv(user=guest.GRADER), f"sudo -n sh -c {shlex.quote(remote)}"]
        self._proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
        )

        def pump() -> None:
            assert self._proc and self._proc.stdout
            for line in self._proc.stdout:
                if not line.startswith("{"):
                    continue
                try:
                    doc = json.loads(line)
                    on_pass(PassResult(phase=Phase.LIVE, results=doc["results"]))
                except (ValueError, KeyError):
                    continue
            if self._proc and self._proc.returncode not in (None, 0, -15):
                on_error((self._proc.stderr.read() if self._proc.stderr else "")[-400:])

        self._thread = threading.Thread(target=pump, daemon=True, name="live-checks")
        self._thread.start()

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        guest.root(self.inst, f"pkill -f norboten_runner.check_runner; rm -rf {guest.GUEST_DIR}")

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None
