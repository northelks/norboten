"""Opt-in telemetry: which check people get stuck on. No identifiers, no free text."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from norboten_api.deps import get_store
from norboten_api.settings import settings
from norboten_api.store import Store

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


class StuckPoint(BaseModel):
    lab_id: str
    base_image: str = ""
    check_id: str
    failed_attempts: int = Field(ge=1, le=1000)
    hint_level: int = Field(default=0, ge=0, le=4)
    minutes: int = Field(default=0, ge=0, le=600)


@router.post("")
async def record(event: StuckPoint, store: Store = Depends(get_store)) -> dict:
    """Record an opt-in stuck point: which check a learner was on and at which hint level. 404 when
    the server has telemetry turned off.
    """
    if not settings().telemetry_enabled:
        raise HTTPException(404, "telemetry is disabled on this server")
    await store.record_event("stuck_point", event.model_dump())
    return {"stored": True}


@router.get("/stuck-points")
async def stuck_points(store: Store = Depends(get_store)) -> list[dict]:
    """What the weekly digest reads: the checks people fail most."""
    counts: dict[tuple[str, str], int] = {}
    for e in await store.events("stuck_point", limit=5000):
        key = (e["lab_id"], e["check_id"])
        counts[key] = counts.get(key, 0) + e.get("failed_attempts", 1)
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    return [{"lab_id": lab, "check_id": check, "failures": n} for (lab, check), n in ranked]
