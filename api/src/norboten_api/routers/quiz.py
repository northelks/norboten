"""The theory banks this server knows. Questions are written into the repository, never here."""

from __future__ import annotations

from fastapi import APIRouter

from norboten.quiz import bank as banks

router = APIRouter(prefix="/quiz", tags=["quiz"])


@router.get("/topics")
async def topics() -> list[dict]:
    """The theory banks: every topic bank and every lab's own, with how many questions each has."""
    return [
        {
            "topic": b.topic,
            "title": b.bank.title,
            "description": b.bank.description,
            "questions": len(b.bank.questions),
            "lab": b.lab_id,
        }
        for b in banks.all_banks()
    ]
