"""Live and replayed terminals.

The recorder POSTs a batch every couple of seconds; viewers either read the whole recording (a
replay) or subscribe to it as it arrives (a live stream, over server-sent events). SSE rather than
WebSockets: the traffic is one-way, it survives a proxy that only understands HTTP, and the
browser reconnects on its own.

Frames reach viewers through Redis (`live.py`): the recorder's POST stores the batch and publishes
it on `play:<id>`, and each viewer's loop is subscribed to that channel. A viewer who arrives late
first gets what is already stored, then what is published; one who opens a session before its
first frame just waits on the channel.

A session is public the moment it starts — that is the point of the Live page — so the TUI asks
first (`P` on a lab) and only then streams.
"""

from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from norboten_api import accounts as acc
from norboten_api import announce
from norboten_api.account_store import AccountStore
from norboten_api.auth import Caller, caller, get_accounts
from norboten_api.deps import get_bus, lab_or_none
from norboten_api.live import Bus
from norboten_api.play_store import FrameBatch, PlaySession, PlayStore

router = APIRouter(prefix="/play", tags=["play"])

#: A comment line every so often keeps proxies from closing a quiet stream.
HEARTBEAT_SECONDS = 15.0

#: A viewer is dropped after this long with nothing to send, so a dead stream does not hold a
#: worker for ever. The browser's own EventSource reconnects if the session is still going.
IDLE_TIMEOUT = 120.0


def get_play(request: Request) -> PlayStore:
    return request.app.state.play


class StartIn(BaseModel):
    lab_id: str
    width: int = Field(ge=20, le=400)
    height: int = Field(ge=5, le=200)


class AppendIn(BaseModel):
    seq: int = Field(ge=0)
    at: float
    events: list[list] = Field(default_factory=list)
    commands: list[dict] = Field(default_factory=list)
    changes: list[dict] = Field(default_factory=list)


class EndIn(BaseModel):
    passed: bool | None = None


def _card(session: PlaySession) -> dict:
    return {
        "session_id": session.session_id,
        "nick": session.nick,
        "country": session.country,
        "lab_id": session.lab_id,
        "lab_title": session.lab_title,
        "width": session.width,
        "height": session.height,
        "started_at": session.started_at,
        "duration": round(session.duration, 1),
        "frames": session.frames,
        "commands": session.commands,
        "live": session.live,
        "passed": session.passed,
        "seed": session.seed,
    }


@router.post("/sessions", status_code=201)
async def start(
    body: StartIn,
    background: BackgroundTasks,
    who: Caller = Depends(caller),
    accounts: AccountStore = Depends(get_accounts),
    play: PlayStore = Depends(get_play),
) -> dict:
    """Open a session. Anyone who can see the site can watch it from here on, and the Telegram
    channel is told (`announce.py`)."""
    user = await accounts.user(who.user_id)
    if user is None:
        raise HTTPException(404, "no profile yet: POST /me to choose a nick")
    lab = lab_or_none(body.lab_id)
    session = PlaySession(
        session_id=secrets.token_urlsafe(12),
        user_id=user.user_id,
        nick=user.nick,
        country=user.country,
        lab_id=body.lab_id,
        lab_title=lab.manifest.title if lab else "",
        width=body.width,
        height=body.height,
    )
    await play.start(session)
    background.add_task(announce.live_session, session)
    return {"session_id": session.session_id}


@router.post("/sessions/{session_id}/frames")
async def append(
    session_id: str,
    body: AppendIn,
    who: Caller = Depends(caller),
    play: PlayStore = Depends(get_play),
    bus: Bus = Depends(get_bus),
) -> dict:
    """Append one batch of frames, commands and diffs to your own live session; it is stored and
    published to viewers at once. 409 once the session has ended.
    """
    session = await play.session(session_id)
    if session is None:
        raise HTTPException(404, "no such session")
    if session.user_id != who.user_id:
        raise HTTPException(403, "not your session")
    batch = FrameBatch.model_validate(body.model_dump())
    updated = await play.append(session_id, batch)
    if updated is None:
        raise HTTPException(409, "the session has ended")
    await bus.publish(_channel(session_id), {"type": "batch", "batch": batch.model_dump()})
    return {"frames": updated.frames, "commands": updated.commands}


@router.post("/sessions/{session_id}/end")
async def end(
    session_id: str,
    body: EndIn,
    who: Caller = Depends(caller),
    play: PlayStore = Depends(get_play),
    bus: Bus = Depends(get_bus),
) -> dict:
    """End your own session, optionally with whether the lab was passed; viewers receive `end`."""
    session = await play.session(session_id)
    if session is None:
        raise HTTPException(404, "no such session")
    if session.user_id != who.user_id:
        raise HTTPException(403, "not your session")
    await play.end(session_id, body.passed)
    ended = await play.session(session_id)
    await bus.publish(
        _channel(session_id), {"type": "end", "duration": round(ended.duration, 1) if ended else 0}
    )
    return {"ended": True}


@router.get("/live")
async def live(
    limit: int = Query(default=12, ge=1, le=50),
    play: PlayStore = Depends(get_play),
) -> dict:
    """Who is working right now, and what finished recently."""
    return {
        "live": [_card(s) for s in await play.live(limit)],
        "recent": [_card(s) for s in await play.recent(limit)],
    }


@router.get("/sessions/{session_id}")
async def recording(session_id: str, play: PlayStore = Depends(get_play)) -> dict:
    """The whole recording: an asciicast header, its events, the commands and the diffs."""
    session = await play.session(session_id)
    if session is None:
        raise HTTPException(404, "no such session")
    batches = await play.batches(session_id)
    return {
        "session": _card(session),
        "header": session.header(),
        "events": [event for batch in batches for event in batch.events],
        "commands": [c for batch in batches for c in batch.commands],
        "changes": [c for batch in batches for c in batch.changes],
        "next_seq": batches[-1].seq if batches else -1,
    }


@router.get("/sessions/{session_id}/stream")
async def stream(
    session_id: str,
    after: int = Query(default=-1),
    play: PlayStore = Depends(get_play),
    bus: Bus = Depends(get_bus),
) -> StreamingResponse:
    """Server-sent events: what is stored, then every batch as it is published, then `end`."""
    session = await play.session(session_id)
    if session is None:
        raise HTTPException(404, "no such session")

    async def events():
        yield _sse("header", session.header())
        # subscribe before reading the store, so a batch arriving in between is not lost
        async with bus.subscribe(_channel(session_id)) as subscription:
            cursor = after
            for batch in await play.batches(session_id, after=cursor):
                cursor = batch.seq
                yield _sse("batch", batch.model_dump())
            current = await play.session(session_id)
            if current is None or current.ended_at is not None:
                yield _sse("end", {"duration": round(current.duration, 1) if current else 0})
                return
            idle = 0.0
            while True:
                message = await subscription.next(HEARTBEAT_SECONDS)
                if message is None:
                    idle += HEARTBEAT_SECONDS
                    if idle >= IDLE_TIMEOUT:
                        yield _sse("idle", {"reason": "no frames for two minutes; reconnect"})
                        return
                    yield ": still here\n\n"
                    continue
                if message["type"] == "end":
                    yield _sse("end", {"duration": message.get("duration", 0)})
                    return
                batch = message["batch"]
                if batch["seq"] <= cursor:  # already sent from the store
                    continue
                cursor = batch["seq"]
                idle = 0.0
                yield _sse("batch", batch)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def _channel(session_id: str) -> str:
    return f"play:{session_id}"


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@router.get("/leaderboard-context/{nick}")
async def context(nick: str, accounts: AccountStore = Depends(get_accounts)) -> dict:
    """What a viewer sees next to a live terminal: whose it is, and how they are rated."""
    user = await accounts.user_by_nick(nick)
    if user is None:
        raise HTTPException(404, "no such profile")
    ratings = await accounts.ratings(user.user_id)
    overall = acc.overall(ratings)
    return {
        "nick": user.nick,
        "country": user.country,
        "rating": round(overall.r),
        "provisional": overall.provisional,
    }
