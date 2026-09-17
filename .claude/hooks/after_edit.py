#!/usr/bin/env python3
"""After an Edit or Write: format a Python file with ruff, and lint the lab a file belongs to.

A PostToolUse hook, in two identical copies: the checkout's (`.claude/settings.json`, which CI's
headless runs load) and the norboten-author plugin's (`hooks/hooks.json`, for a fork or a clone
with the plugin installed). Where both are registered, the plugin's copy steps aside.

It reads the tool call as JSON on stdin and uses the tools in the checkout's own `.venv` — no
`uv sync` on every edit, and nothing at all where there is no venv (a CI runner), so it never gets
in a job's way. A lab that stops passing `norboten dev lint`
exits 2: the tool has already run, and the lint errors are shown to Claude to fix.

Standard library only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def lab_of(path: Path, labs: Path) -> Path | None:
    """The lab directory holding `path` (the nearest parent with a lab.yaml), not a draft or the
    template. `labs` is `labs/` or the private `rated/`, whose labs have the same shape."""
    try:
        parts = path.relative_to(labs).parts
    except ValueError:
        return None
    if not parts or parts[0].startswith("_"):
        return None  # labs/_template, labs/_drafts
    for parent in [path.parent, *path.parent.parents]:
        if parent == labs:
            return None
        if (parent / "lab.yaml").is_file():
            return parent
    return None


def main() -> int:
    call = json.load(sys.stdin)
    file_path = (call.get("tool_input") or {}).get("file_path")
    if not file_path:
        return 0
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or call.get("cwd") or ".").resolve()
    own = project / ".claude" / "hooks" / "after_edit.py"
    if own.is_file() and own.resolve() != Path(__file__).resolve():
        return 0  # the plugin's copy, in a checkout that registers its own: that one runs
    path = Path(file_path).resolve()
    venv = project / ".venv" / "bin"
    if project not in path.parents or not venv.is_dir():
        return 0

    if path.suffix == ".py" and (venv / "ruff").is_file():
        subprocess.run(
            [venv / "ruff", "format", "--force-exclude", "--quiet", path],
            cwd=project,
            capture_output=True,
        )

    lab = lab_of(path, project / "labs") or lab_of(path, project / "rated")
    if lab and (venv / "norboten").is_file():
        lint = subprocess.run(
            [venv / "norboten", "dev", "lint", lab],
            cwd=project,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if lint.returncode != 0:
            print(f"norboten dev lint {lab.relative_to(project)} fails:", file=sys.stderr)
            print((lint.stdout + lint.stderr).strip()[-2000:], file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
