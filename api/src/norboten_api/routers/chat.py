"""The chat consultant: `/chat` for one answer, `/chat/stream` for one that arrives as it is read.

The widget on every page of the site talks to this. Answers stream as server-sent events because a
paragraph that appears a few words at a time reads as thinking rather than as latency — and
because the same mechanism already carries the live terminals.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from norboten.questions import providers
from norboten_api import live
from norboten_api.agents import consultant
from norboten_api.deps import client_key, get_bus, get_store, lab_or_none, solution_text
from norboten_api.live import Bus
from norboten_api.settings import settings
from norboten_api.store import Store

router = APIRouter(prefix="/chat", tags=["chat"])

#: How much of an answer goes out at a time. The providers here return a whole answer, so this is
#: honest pacing of something already complete, not a pretend token stream.
CHUNK_WORDS = 18


class Ask(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    lab_id: str | None = None  # what the reader is looking at; context only


def _context(lab_id: str | None) -> tuple[str | None, str]:
    lab = lab_or_none(lab_id) if lab_id else None
    if lab is None:
        return None, ""
    return lab.manifest.title, solution_text(lab.id)


@router.get("/faq")
async def faq() -> dict:
    """The chips under the input: what people actually arrive wanting to know."""
    return {
        "chips": FAQ,
        "categories": [{"title": title, "chips": chips} for title, chips in FAQ_GROUPS],
    }


async def _allowed(request: Request, bus: Bus) -> None:
    if await live.limited(bus, "chat", client_key(request), settings().chat_per_minute):
        raise HTTPException(429, "too many questions this minute; the docs are faster anyway")


@router.post("")
async def ask(
    body: Ask,
    request: Request,
    store: Store = Depends(get_store),
    bus: Bus = Depends(get_bus),
) -> dict:
    """Ask the consultant once and wait for the whole answer: the reply, the passages it used, and
    whether the guard blocked it. The streaming form is `/chat/stream`.
    """
    await _allowed(request, bus)
    title, solution = _context(body.lab_id)
    try:
        # a model call blocks for seconds (minutes, on a CPU-only Ollama): off the event loop
        answer = await asyncio.to_thread(
            consultant.answer, body.question, lab_title=title, solution_text=solution
        )
    except providers.NoProvider as e:
        raise HTTPException(503, str(e)) from None
    except providers.ProviderError as e:
        raise HTTPException(502, str(e)) from None
    await store.record_event("chat", {"lab": body.lab_id, "blocked": answer.blocked})
    return answer.model_dump()


@router.get("/stream")
async def stream(
    request: Request,
    question: str = Query(min_length=3, max_length=500),
    lab_id: str | None = Query(default=None),
    store: Store = Depends(get_store),
    bus: Bus = Depends(get_bus),
) -> StreamingResponse:
    """`sources` first — so a reader can start checking before the answer lands — then `token`s."""
    await _allowed(request, bus)
    title, solution = _context(lab_id)

    async def events():
        try:
            answer = await asyncio.to_thread(
                consultant.answer, question, lab_title=title, solution_text=solution
            )
        except providers.NoProvider:
            yield _sse("sources", {"sources": consultant.sources(_search(question))})
            yield _sse(
                "token",
                {
                    "text": "This server has no model configured, so I can only point at the "
                    "passages above — they are the ones that match your question."
                },
            )
            yield _sse("end", {})
            return
        except providers.ProviderError as e:
            # Not "error": EventSource dispatches its own connection failures under that name, so
            # a server-sent event called "error" is indistinguishable from a dropped connection.
            yield _sse("failed", {"message": str(e)})
            yield _sse("end", {})
            return

        yield _sse("sources", {"sources": answer.sources})
        for piece in _chunks(answer.answer):
            yield _sse("token", {"text": piece})
        yield _sse("end", {"blocked": answer.blocked})
        await store.record_event("chat", {"lab": lab_id, "blocked": answer.blocked})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def _search(question: str):
    from norboten_api import retrieval

    return retrieval.index().search(question, consultant.CONTEXT_PASSAGES)


def _chunks(text: str, size: int = CHUNK_WORDS) -> list[str]:
    words = text.split(" ")
    out = []
    for i in range(0, len(words), size):
        piece = " ".join(words[i : i + size])
        out.append(piece if i + size >= len(words) else piece + " ")
    return out


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


#: Fifty questions people actually arrive with, in the sections the widget shows them under.
#: Chips rather than a FAQ page: one tap asks, so nobody has to guess what this thing knows.
FAQ_GROUPS: list[tuple[str, list[str]]] = [
    (
        "The idea",
        [
            "What makes this different from a browser-based Linux course?",
            "Why a virtual machine instead of a container?",
            "Why is everything so dark?",
            "What is a journal, and how is it different from the docs?",
        ],
    ),
    (
        "Labs and grading",
        [
            "How is a lab graded?",
            "What is the reboot check, and why does it matter?",
            "How do I reset a lab I have broken beyond repair?",
            "How long does the first lab take?",
            "What is inside a lab directory?",
            "How does the solvability gate work?",
            "What stops a lab from being unsolvable?",
        ],
    ),
    (
        "The tutor and hints",
        [
            "Will the tutor tell me the answer if I ask nicely?",
            "How do hints work?",
        ],
    ),
    (
        "Your machine",
        [
            "What is left on my machine if I delete Norboten?",
            "Can a lab VM see my files?",
            "How much disk does this need?",
            "Does it work on Apple Silicon?",
            "Does it work on Windows?",
            "Do I need to be online?",
            "Which base images are there, and how big are they?",
        ],
    ),
    (
        "Tracks and the exam",
        [
            "What is in the RHCSA track?",
            "Is the exam simulation timed like the real exam?",
            "How close is this to the real EX200?",
            "What is the automation track about?",
        ],
    ),
    (
        "Theory questions",
        [
            "How are theory questions verified?",
            "What does 'verified by two models' mean?",
            "Can I flag a question that is wrong?",
        ],
    ),
    (
        "Ratings and profiles",
        [
            "How do ratings work?",
            "What is Glicko-2, and why use it?",
            "Why does my rating have a ± on it?",
            "What makes an attempt rated?",
            "How long do I get for a lab?",
            "Does an unrated lab affect my rating?",
            "What are the nineteen topics?",
            "How is the radar chart calculated?",
            "What is on the contributions heatmap?",
        ],
    ),
    (
        "Account and privacy",
        [
            "Do I need an account?",
            "How does signing in work?",
            "Where are my tokens stored?",
            "What does the server know about me?",
            "Is telemetry on by default?",
        ],
    ),
    (
        "Recording and live sessions",
        [
            "What is recorded when I record a session with p?",
            "Who can watch my live session?",
            "How long are recordings kept?",
            "Are the file diffs taken inside the VM?",
        ],
    ),
    (
        "Journals",
        [
            "Can I read a journal on paper?",
        ],
    ),
    (
        "Running and contributing",
        [
            "Can I write my own lab?",
            "What does the hosted side cost to run?",
            "Can I self-host all of it?",
            "How do I report a lab that stopped working?",
        ],
    ),
]
FAQ = [question for _, questions in FAQ_GROUPS for question in questions]
