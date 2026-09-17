"""Where things live, on the host."""

from __future__ import annotations

import os
from importlib import resources
from pathlib import Path


def norboten_home() -> Path:
    """Everything Norboten writes on the host: Lima, images, lab cache, sessions."""
    return Path(os.environ.get("NORBOTEN_HOME", Path.home() / ".norboten"))


def repo_root() -> Path | None:
    """The source checkout this package runs from, if any (development mode)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "images" / "registry.yaml").is_file() and (parent / "labs").is_dir():
            return parent
    return None


def registry_file() -> Path:
    root = repo_root()
    if root is not None:
        return root / "images" / "registry.yaml"
    packaged = resources.files("norboten") / "data" / "registry.yaml"
    return Path(str(packaged))


def packaged_content() -> Path | None:
    """The labs, question banks, journals and recordings a wheel carries (cli/pyproject.toml)."""
    path = Path(str(resources.files("norboten") / "data" / "content"))
    return path if path.is_dir() else None


def content_root() -> Path | None:
    """Where labs/, quizzes/, journals/ and site/streams/ are read from: the checkout, else the
    copy packaged in the wheel, so an installed norboten works before anything is pulled.
    """
    return repo_root() or packaged_content()


def local_labs_dir() -> Path | None:
    """Labs from NORBOTEN_LABS_DIR, a checkout, or the wheel. The first two take precedence over
    the OCI cache; a packaged lab yields to a newer version pulled into the cache.
    """
    env = os.environ.get("NORBOTEN_LABS_DIR")
    if env:
        return Path(env)
    root = content_root()
    return root / "labs" if root is not None else None


def rated_checked_out() -> Path:
    """The rated directory an author writes into; raises when it is not there to write into.

    An empty `rated/` is what a clone without access to the private repository has — writing rated
    material there would put it in the public tree, so it is refused (docs/rated-labs.md)."""
    root = rated_dir()
    if root is None or not (root / "README.md").is_file():
        raise RuntimeError(
            "rated/ is not checked out: rated work goes into the private repository — "
            "`git submodule update --init rated` with access to it, or leave it unrated"
        )
    return root


def rated_dir() -> Path | None:
    """The rated labs and banks: NORBOTEN_RATED_DIR (the server's read-only mount), else a
    checkout's `rated/` submodule — which has content only for someone with access to the private
    repository (docs/rated-labs.md). Never packaged, never pulled into ~/.norboten.
    """
    env = os.environ.get("NORBOTEN_RATED_DIR")
    if env:
        return Path(env)
    root = repo_root()
    return root / "rated" if root is not None else None
