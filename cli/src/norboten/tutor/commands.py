"""What the learner typed during an attempt, for the post-mortem — from two places that differ.

* **Recordings** (`p` or `P` on the lab): ~/.norboten/plays/<lab>-<time>.log.json. Exact and timed
  to the second, but only for the shells that were recorded.
* **Shell history** on the machine (the runner's fact bundle reads ~/.bash_history and root's):
  every shell, `o` or your own ssh, but untimed, bash only, and anyone can edit it.

`merged` keeps every recorded command with its time, then the history lines that were not already
recorded, each labelled with where it came from, so the reviewer can weigh them.
"""

from __future__ import annotations

import json
import re

from norboten.play.session import plays_dir

LIMIT = 80


def recorded(lab_id: str, since: float) -> list[tuple[float, str]]:
    """(seconds since `since`, command) from every recording of this lab made after `since`."""
    out: list[tuple[float, str]] = []
    for path in sorted(plays_dir().glob(f"{lab_id}-*.log.json")):
        try:
            log = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        started = float(log.get("started_at") or 0)
        if log.get("lab_id") != lab_id or started < since - 60:
            continue
        for command in log.get("commands", []):
            text = str(command.get("text", "")).strip()
            if text:
                out.append((max(0.0, started + float(command.get("at", 0)) - since), text))
    out.sort()
    return out


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def merged(lab_id: str, since: float, history: list[str]) -> list[str]:
    timed = recorded(lab_id, since)
    seen = {_flat(text) for _, text in timed}
    lines = [f"[recorded +{int(at) // 60}:{int(at) % 60:02d}] {text}" for at, text in timed]
    lines += [f"[history] {line}" for line in history if line.strip() and _flat(line) not in seen]
    return lines[-LIMIT:]
