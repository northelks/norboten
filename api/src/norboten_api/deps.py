"""Shared dependencies: the store, and the labs the server serves."""

from __future__ import annotations

from functools import lru_cache

from fastapi import Request

from norboten.labs.manifest import Lab, LabError
from norboten.labs.store import all_labs
from norboten_api.store import Store


def get_store(request: Request) -> Store:
    return request.app.state.store


def get_bus(request: Request):
    return request.app.state.bus


def get_play(request: Request):
    return request.app.state.play


def get_rated(request: Request):
    return request.app.state.rated


def get_rated_quiz(request: Request):
    return request.app.state.rated_quiz


def client_key(request: Request) -> str:
    """Who a rate limit counts: the address Caddy saw, not Caddy's own."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@lru_cache
def catalogue() -> dict[str, Lab]:
    return {lab.id: lab for lab in all_labs()}


def lab_or_none(lab_id: str) -> Lab | None:
    labs = catalogue()
    if lab_id in labs:
        return labs[lab_id]
    return next((lab for lab in labs.values() if lab.manifest.short_id == lab_id), None)


def solution_text(lab_id: str, image: str | None = None) -> str:
    """Read a lab's reference solution — server-side only, never returned to a client."""
    lab = lab_or_none(lab_id)
    if lab is None:
        return ""
    try:
        return lab.solution_for(image or lab.manifest.base_images[0]).read_text()
    except (OSError, LabError):
        return ""


@lru_cache
def rated_catalogue() -> dict[str, Lab]:
    """The rated labs mounted beside this server (settings.rated_dir); empty when there are none,
    which is what a self-hosted server has (docs/rated-labs.md)."""
    from pathlib import Path

    from norboten.labs.store import rated_labs
    from norboten_api.settings import settings

    root = settings().rated_dir
    if not root:
        return {}
    return {lab.id: lab for lab in rated_labs(Path(root))}


def rated_lab_or_none(lab_id: str) -> Lab | None:
    labs = rated_catalogue()
    if lab_id in labs:
        return labs[lab_id]
    return next((lab for lab in labs.values() if lab.manifest.short_id == lab_id), None)


@lru_cache
def rated_banks() -> dict:
    """The rated question banks beside this server: `<rated_dir>/quizzes/<topic>.yaml`, by topic."""
    from pathlib import Path

    from norboten.quiz.bank import load
    from norboten_api.settings import settings

    root = settings().rated_dir
    folder = Path(root) / "quizzes" if root else None
    if folder is None or not folder.is_dir():
        return {}
    banks = [load(path) for path in sorted(folder.glob("*.yaml"))]
    return {b.topic: b for b in banks}
