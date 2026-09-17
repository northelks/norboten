"""Load a lab's break/check scripts as modules, in file order."""

from __future__ import annotations

import importlib.util
import os
import re
from types import ModuleType

_NAME = re.compile(r"^\d{2}_[a-z0-9_]+\.py$")


def scripts(lab_dir: str, kind: str) -> list[tuple[str, str]]:
    """[(id, path)] for lab_dir/<kind>/NN_name.py, sorted."""
    d = os.path.join(lab_dir, kind)
    if not os.path.isdir(d):
        return []
    return [(f[:-3], os.path.join(d, f)) for f in sorted(os.listdir(d)) if _NAME.match(f)]


def load(path: str, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"norboten_lab_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
