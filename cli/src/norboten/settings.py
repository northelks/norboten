"""Local settings: what this installation remembers between runs, such as a finished setup."""

from __future__ import annotations

import json
import os
from pathlib import Path

from norboten.paths import norboten_home


def _path() -> Path:
    return norboten_home() / "settings.json"


def load() -> dict:
    try:
        data = json.loads(_path().read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(**changes) -> dict:
    data = load() | changes
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)
    return data


def setup_done() -> bool:
    return bool(load().get("setup_done"))
