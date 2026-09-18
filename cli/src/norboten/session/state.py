"""The lab session state machine.

    pulled -> booted -> broken -> working -> checked -> passed
                           ^         |          |
                           |         +<---------+   (a failed check returns to working)
                           +-------- reset ---------+

`surrendered` is terminal like `passed`: the solution becomes visible and grading stops counting.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field, fields
from enum import StrEnum
from pathlib import Path

from norboten.paths import norboten_home


class State(StrEnum):
    PULLED = "pulled"
    BOOTED = "booted"
    BROKEN = "broken"
    WORKING = "working"
    CHECKED = "checked"
    PASSED = "passed"
    SURRENDERED = "surrendered"


ALLOWED: dict[State, set[State]] = {
    State.PULLED: {State.BOOTED},
    State.BOOTED: {State.BROKEN},
    State.BROKEN: {State.WORKING, State.CHECKED, State.BROKEN, State.SURRENDERED},
    State.WORKING: {State.CHECKED, State.BROKEN, State.SURRENDERED},
    State.CHECKED: {State.WORKING, State.PASSED, State.BROKEN, State.SURRENDERED},
    State.PASSED: {State.BROKEN},
    State.SURRENDERED: {State.BROKEN},
}


class InvalidTransition(RuntimeError):
    pass


@dataclass
class Attempt:
    at: float
    score_percent: int
    passed: bool


@dataclass
class Session:
    lab_id: str
    lab_version: str
    image: str
    instance: str
    state: State = State.PULLED
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    hint_levels: dict[str, int] = field(default_factory=dict)
    attempts: list[Attempt] = field(default_factory=list)
    learner: str = ""
    clock_started_at: float = 0.0  # when the faults were applied; a lab's time limit runs from here
    rated: bool = False  # a rated lab's attempt, graded on the server (docs/lab-spec.md §13)
    # the server's attempt: id, nonce, key, clock — the key signs this attempt's records only
    rated_attempt: dict = field(default_factory=dict)
    rated_outcome: str = ""  # "passed", "failed", "abandoned", "expired" once the server closed it

    def advance(self, new: State) -> None:
        if new not in ALLOWED[self.state]:
            raise InvalidTransition(f"cannot go from {self.state.value} to {new.value}")
        self.state = new
        self.updated_at = time.time()

    @property
    def finished(self) -> bool:
        return self.state in (State.PASSED, State.SURRENDERED)

    # -- persistence -----------------------------------------------------------------------

    @staticmethod
    def path_for(lab_id: str) -> Path:
        return norboten_home() / "sessions" / f"{lab_id}.json"

    def save(self) -> None:
        path = self.path_for(self.lab_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["state"] = self.state.value
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        os.replace(tmp, path)

    @classmethod
    def load(cls, lab_id: str) -> Session | None:
        path = cls.path_for(lab_id)
        if not path.is_file():
            return None
        data = json.loads(path.read_text())
        data["state"] = State(data["state"])
        data["attempts"] = [Attempt(**_known(Attempt, a)) for a in data.get("attempts", [])]
        # a newer norboten may have written fields this one does not know: an older install
        # (a downgrade, a stale uv tool) keeps working instead of refusing every session
        return cls(**_known(cls, data))

    def delete(self) -> None:
        self.path_for(self.lab_id).unlink(missing_ok=True)


def _known(kind: type, data: dict) -> dict:
    names = {f.name for f in fields(kind)}
    return {k: v for k, v in data.items() if k in names}


def all_sessions() -> list[Session]:
    d = norboten_home() / "sessions"
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        if "." in p.stem:  # <lab>.last.json is the last grade report, not a session
            continue
        s = Session.load(p.stem)
        if s:
            out.append(s)
    return out
