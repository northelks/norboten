"""Loading labs and the base image registry from disk."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml
from pydantic import ValidationError

from norboten.models import Hints, LabManifest, Registry
from norboten.paths import registry_file


class LabError(Exception):
    """A lab or the registry is malformed. The message is meant for a lab author."""


def _read_yaml(path: Path) -> object:
    try:
        return yaml.safe_load(path.read_text())
    except FileNotFoundError:
        raise LabError(f"{path}: file not found") from None
    except yaml.YAMLError as e:
        raise LabError(f"{path}: invalid YAML: {e}") from None


def _format(e: ValidationError) -> str:
    lines = []
    for err in e.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        lines.append(f"  {loc}: {err['msg']}")
    return "\n".join(lines)


def load_registry(path: Path | None = None) -> Registry:
    path = path or registry_file()
    try:
        return Registry.model_validate(_read_yaml(path))
    except ValidationError as e:
        raise LabError(f"{path}: invalid registry\n{_format(e)}") from None


@cache
def default_registry() -> Registry:
    return load_registry()


def parse_manifest(path: Path, registry: Registry | None = None) -> LabManifest:
    registry = registry or default_registry()
    try:
        return LabManifest.model_validate(_read_yaml(path), context={"registry": registry})
    except ValidationError as e:
        raise LabError(f"{path}: invalid lab manifest\n{_format(e)}") from None


def parse_hints(path: Path) -> Hints:
    try:
        return Hints.model_validate(_read_yaml(path))
    except ValidationError as e:
        raise LabError(f"{path}: invalid hints\n{_format(e)}") from None


@dataclass(frozen=True)
class Lab:
    """A lab on disk: its directory plus the parsed manifest."""

    path: Path
    manifest: LabManifest

    @classmethod
    def load(cls, path: Path, registry: Registry | None = None) -> Lab:
        return cls(path=path, manifest=parse_manifest(path / "lab.yaml", registry))

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def briefing(self) -> str:
        return (self.path / "briefing.md").read_text()

    @property
    def hints(self) -> Hints:
        return parse_hints(self.path / "hints.yaml")

    def solution_for(self, image_id: str) -> Path:
        specific = self.path / "solution" / f"{image_id}.sh"
        return specific if specific.is_file() else self.path / "solution" / "solution.sh"


def discover(root: Path, registry: Registry | None = None) -> list[Lab]:
    """Every lab under root (a directory holding lab.yaml), skipping _template."""
    labs = []
    for manifest in sorted(root.rglob("lab.yaml")):
        if "_template" in manifest.parts:
            continue
        labs.append(Lab.load(manifest.parent, registry))
    return labs
