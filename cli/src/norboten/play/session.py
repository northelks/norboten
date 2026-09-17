"""Play — work on a lab with the terminal recorded (`p` on a lab), and optionally streamed (`P`).

The pieces: the PTY recorder captures the session, the watcher turns each command into a diff, and
this module decides where any of it goes. Three modes, in order of how much leaves the machine:

* **recorded** (default): an asciicast file and a command log under `~/.norboten/plays/`. Nothing
  leaves the machine.
* **streamed** (`P`): batches are POSTed to the API every couple of seconds, and the session
  appears on the site's Live page while it runs. It needs a signed-in account.
* **neither** (`o`): just a shell.

Uploads happen on a worker thread. If the API is unreachable, the batch is dropped and the shell
carries on: a recording is worth something, but not the session.
"""

from __future__ import annotations

import contextlib
import json
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from norboten import auth
from norboten.lima.instance import Instance
from norboten.paths import norboten_home
from norboten.play import watch
from norboten.play.recorder import Command, Frame, Recording, record, terminal_size
from norboten.tutor.client import ApiUnavailable, base_url

#: Diffs are only asked for when the learner actually ran something, and at most this often: a
#: `git add -A` over /etc costs the guest a few hundred milliseconds.
DIFF_EVERY = 2.0


def plays_dir() -> Path:
    return norboten_home() / "plays"


@dataclass
class Upload:
    """The API side of a streamed session. Silent about failures by design."""

    lab_id: str
    session_id: str = ""
    failures: int = 0
    seq: int = 0

    def start(self, width: int, height: int) -> str:
        r = httpx.post(
            f"{base_url()}/play/sessions",
            json={"lab_id": self.lab_id, "width": width, "height": height},
            headers=auth.headers(),
            timeout=30,
        )
        if r.status_code == 404:
            raise ApiUnavailable("no profile yet — choose a nick in the You section (7)")
        if r.status_code >= 400:
            raise ApiUnavailable(f"the API answered HTTP {r.status_code}")
        self.session_id = r.json()["session_id"]
        return self.session_id

    def push(self, frames: list[Frame], commands: list[Command], changes: list[dict]) -> None:
        if not self.session_id:
            return
        payload = {
            "seq": self.seq,
            "at": frames[0].at if frames else 0.0,
            "events": [f.as_event() for f in frames],
            "commands": [{"at": round(c.at, 3), "text": c.text} for c in commands],
            "changes": changes,
        }
        self.seq += 1
        try:
            r = httpx.post(
                f"{base_url()}/play/sessions/{self.session_id}/frames",
                json=payload,
                headers=auth.headers(),
                timeout=15,
            )
            if r.status_code >= 400:
                self.failures += 1
        except httpx.HTTPError:
            self.failures += 1

    def end(self, passed: bool | None = None) -> None:
        if not self.session_id:
            return
        with contextlib.suppress(httpx.HTTPError):
            httpx.post(
                f"{base_url()}/play/sessions/{self.session_id}/end",
                json={"passed": passed},
                headers=auth.headers(),
                timeout=15,
            )


@dataclass
class Play:
    """One recorded session: the shell, the watcher, the log and (maybe) the upload."""

    inst: Instance
    lab_id: str
    title: str = ""
    stream: bool = False
    watch_paths: tuple[str, ...] = watch.DEFAULT_PATHS
    upload: Upload | None = None
    armed: list[str] = field(default_factory=list)
    changes: list[dict] = field(default_factory=list)
    _queue: queue.Queue = field(default_factory=queue.Queue)
    _worker: threading.Thread | None = None
    _last_diff: float = 0.0

    # -- the background worker -------------------------------------------------------------

    def _serve(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                self._queue.task_done()
                return
            frames, commands = item
            changes = self._collect_changes(commands)
            if self.upload is not None:
                self.upload.push(frames, commands, changes)
            self._queue.task_done()

    def _collect_changes(self, commands: list[Command]) -> list[dict]:
        """Ask the guest what changed, and blame it on the last command that ran."""
        if not self.armed or not commands:
            return []
        now = time.monotonic()
        if now - self._last_diff < DIFF_EVERY:
            return []
        self._last_diff = now
        out = []
        for change in watch.changes(self.inst, self.armed):
            entry = {
                "path": change.path,
                "diff": change.diff,
                "truncated": change.truncated,
                "command": commands[-1].text,
                "at": round(commands[-1].at, 3),
            }
            out.append(entry)
            self.changes.append(entry)
        return out

    # -- the session -----------------------------------------------------------------------

    def run(self, say=lambda _: None) -> tuple[Recording, int]:
        cols, rows = terminal_size()
        self.armed = watch.arm(self.inst, self.watch_paths)
        if self.watch_paths and not self.armed:
            say("the guest has no git, so file changes will not be recorded")

        if self.stream:
            self.upload = Upload(lab_id=self.lab_id)
            self.upload.start(cols, rows)
            say(f"streaming live · {base_url()}/play/{self.upload.session_id}")

        self._worker = threading.Thread(target=self._serve, daemon=True)
        self._worker.start()

        argv = self.inst.ssh_argv(tty=True)
        try:
            recording, code = record(
                argv,
                title=self.title or self.lab_id,
                on_frames=lambda frames, commands: self._queue.put((frames, commands)),
            )
        finally:
            self._queue.put(None)
            if self._worker is not None:
                self._worker.join(timeout=30)
            if self.upload is not None:
                self.upload.end()
        return recording, code

    def save(self, recording: Recording) -> Path:
        """Write the asciicast and the command/diff log next to each other."""
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(recording.started_at))
        target = plays_dir() / f"{self.lab_id}-{stamp}"
        recording.write(target.with_suffix(".cast"))
        log = {
            "lab_id": self.lab_id,
            "started_at": recording.started_at,
            "duration": round(recording.duration, 2),
            "commands": [{"at": round(c.at, 3), "text": c.text} for c in recording.commands],
            "changes": self.changes,
        }
        target.with_suffix(".log.json").write_text(json.dumps(log, indent=2) + "\n")
        return target.with_suffix(".cast")
