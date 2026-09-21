#!/usr/bin/env python3
"""Which labs a change touches, as a GitHub Actions matrix of (lab, image) pairs.

    python .github/scripts/changed_labs.py <base-ref>
    python .github/scripts/changed_labs.py --all

A change under labs/<lab>/ validates that lab. A change to the runner, the CLI's guest-facing
code, the baseline role or the image registry validates everything — those touch every lab.
`--all` validates everything regardless: the weekly scheduled run. So does a base this checkout
does not have — the gate errs towards running.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVERYTHING = (
    "runner/",
    "cli/src/norboten/session/",
    "cli/src/norboten/lima/",
    "cli/src/norboten/models.py",
    "images/registry.yaml",
    "ansible/roles/lab_baseline/",
)


def known(ref: str) -> bool:
    """A push's `before` is unknown after a force push, and all zeros for a new branch."""
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        capture_output=True,
        cwd=ROOT,
    )
    return probe.returncode == 0


def changed_files(base: str) -> list[str]:
    out = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


def main() -> int:
    sys.path.insert(0, str(ROOT / "cli" / "src"))
    from norboten.labs.manifest import discover

    base = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
    labs = {lab.id: lab for lab in discover(ROOT / "labs")}
    everything = base == "--all" or not known(base)
    files = [] if everything else changed_files(base)

    if everything or any(f.startswith(EVERYTHING) for f in files):
        selected = set(labs)
    else:
        selected = {
            lab_id
            for lab_id, lab in labs.items()
            for f in files
            if f.startswith(str(lab.path.relative_to(ROOT)) + "/")
        }

    matrix = [
        {"lab": lab_id, "image": image, "runtime": labs[lab_id].manifest.runtime}
        for lab_id in sorted(selected)
        for image in labs[lab_id].manifest.base_images
    ]
    output = os.environ.get("GITHUB_OUTPUT")
    payload = json.dumps({"include": matrix})
    if output:
        with open(output, "a") as f:
            f.write(f"matrix={payload}\n")
            f.write(f"any={'true' if matrix else 'false'}\n")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
