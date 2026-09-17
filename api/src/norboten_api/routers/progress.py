"""Opt-in progress sync. Anonymous by default: the client sends an id it generated itself."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from norboten_api.deps import get_store
from norboten_api.store import Store

router = APIRouter(prefix="/progress", tags=["progress"])


class Attempt(BaseModel):
    client_id: str = Field(min_length=8, max_length=64)
    lab_id: str
    score_percent: int = Field(ge=0, le=100)
    passed: bool
    minutes: int = 0
    base_image: str = ""


@router.post("")
async def record(attempt: Attempt, store: Store = Depends(get_store)) -> dict:
    """Store an anonymous, opt-in progress event under a random client id. No account involved."""
    await store.record_event("progress", attempt.model_dump())
    return {"stored": True}


@router.get("/{client_id}")
async def read(client_id: str, store: Store = Depends(get_store)) -> list[dict]:
    """Read back the progress events recorded under a client id."""
    return [e for e in await store.events("progress", limit=500) if e.get("client_id") == client_id]
