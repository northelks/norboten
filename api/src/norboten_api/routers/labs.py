"""The catalogue: what labs exist, and what a lab asks of the learner."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from norboten_api.deps import catalogue, lab_or_none

router = APIRouter(prefix="/labs", tags=["labs"])


@router.get("")
async def list_labs() -> list[dict]:
    """Every lab the server knows: id, short id, title, track, difficulty, estimated minutes, base
    images and topics.
    """
    out = []
    for lab in catalogue().values():
        m = lab.manifest
        out.append(
            {
                "id": m.id,
                "short_id": m.short_id,
                "title": m.title,
                "track": m.track.value,
                "difficulty": m.difficulty,
                "estimated_minutes": m.estimated_minutes,
                "base_images": m.base_images,
                "objectives": m.objectives,
                "version": m.version,
            }
        )
    return out


@router.get("/{lab_id}")
async def get_lab(lab_id: str) -> dict:
    """One lab's manifest and briefing, by id or short id. Hints come with the lab package; the
    reference solution never leaves the server.
    """
    lab = lab_or_none(lab_id)
    if lab is None:
        raise HTTPException(404, f"no lab {lab_id!r}")
    # briefing and manifest only: hints come from the lab package, solutions never leave the server
    return {"manifest": lab.manifest.model_dump(mode="json"), "briefing": lab.briefing}
