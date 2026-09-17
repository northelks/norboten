"""Local progress: theory results per topic. Never sent anywhere unless the learner opts in."""

from __future__ import annotations

import json
import os
from pathlib import Path

from norboten.paths import norboten_home


def _path() -> Path:
    return norboten_home() / "progress.json"


def load() -> dict:
    try:
        return json.loads(_path().read_text())
    except (OSError, ValueError):
        return {"theory": {}}


def record_theory(topic: str, correct: bool, streak: int) -> dict:
    data = load()
    t = data.setdefault("theory", {}).setdefault(
        topic, {"answered": 0, "correct": 0, "best_streak": 0}
    )
    t["answered"] += 1
    t["correct"] += int(correct)
    t["best_streak"] = max(t["best_streak"], streak)
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)
    return t
