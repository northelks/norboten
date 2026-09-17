"""The rated half of the catalogue must never leave in a published artefact.

A container image is a tar of files and a wheel is a zip: whatever is copied into either is public
the moment it is pushed, and layers cannot be taken back. So these check the recipes themselves —
the API's Dockerfile, its .dockerignore, the wheel's force-include — rather than trusting a setting
to be remembered (docs/rated-labs.md).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_the_api_image_copies_nothing_from_rated() -> None:
    dockerfile = (ROOT / "api/Dockerfile").read_text()
    sources = [
        part
        for line in dockerfile.splitlines()
        if line.strip().startswith("COPY") and "--from=" not in line
        for part in line.split()[1:-1]
    ]
    assert sources, "the Dockerfile copies something"
    assert not any(s.rstrip("/") in (".", "rated") or s.startswith("rated") for s in sources), (
        sources
    )


def test_the_docker_context_leaves_rated_out() -> None:
    ignored = (ROOT / ".dockerignore").read_text().split()
    assert "rated" in ignored or "rated/" in ignored


def test_the_wheel_carries_no_rated_material() -> None:
    pyproject = tomllib.loads((ROOT / "cli/pyproject.toml").read_text())
    included = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"]
    assert not any(re.search(r"(^|/)rated(/|$)", k) for k in included), included


def test_the_server_mounts_rated_content_read_only_beside_the_image() -> None:
    api = yaml.safe_load((ROOT / "deploy/compose.yaml").read_text())["services"]["api"]
    mounts = [m for m in api.get("volumes", []) if ":/app/rated" in m]
    assert len(mounts) == 1 and mounts[0].endswith(":ro"), mounts
    assert api["environment"]["NORBOTEN_RATED_DIR"] == "/app/rated"
