"""Linking Discord to an account, from the account page — optional, and only for the digest.

1. `POST /auth/discord/start` `{join}` with the account's token — a `discord-link` flow is kept
   (`pending.py`) and the page gets Discord's consent URL to go to. "Join the Norboten server" is
   `join`, off unless the learner ticks it; only then is `guilds.join` asked for;
2. `GET /auth/discord/callback` — Discord's code becomes the Discord user id (and a join, if asked);
   the browser goes back to the account page with `#discord=linked`, `joined`, `taken`, `denied` or
   `error` in the fragment;
3. `DELETE /auth/discord` — unlinks, and turns the digest off with it.

A start is a POST with the token rather than a link the browser follows, because a browser does not
send a bearer token on a navigation — this way the flow is bound to the account before it leaves.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from norboten_api import discord, live
from norboten_api.auth import Caller, caller, get_credentials, get_pending
from norboten_api.credentials import CredentialStore, DiscordTaken
from norboten_api.deps import client_key, get_bus
from norboten_api.live import Bus
from norboten_api.pending import PendingStore
from norboten_api.settings import settings

router = APIRouter(prefix="/auth/discord", tags=["auth"])
log = logging.getLogger("norboten_api.discord")


class StartIn(BaseModel):
    join: bool = False


def _callback_uri() -> str:
    return f"{settings().api_url.rstrip('/')}/auth/discord/callback"


def _back(result: str) -> RedirectResponse:
    return RedirectResponse(f"{settings().site_url.rstrip('/')}/account/#discord={result}", 302)


@router.post("/start")
async def start(
    body: StartIn,
    request: Request,
    who: Caller = Depends(caller),
    pending: PendingStore = Depends(get_pending),
    credentials: CredentialStore = Depends(get_credentials),
    bus: Bus = Depends(get_bus),
) -> dict:
    """Where to send the browser to link Discord to this account."""
    if not discord.configured():
        raise HTTPException(503, "Discord is not configured on this server")
    if await credentials.identity(who.user_id) is None:
        raise HTTPException(404, "no credentials for this identity")
    if await live.limited(bus, "discord-link", client_key(request), 10):
        raise HTTPException(429, "too many attempts; wait a minute")
    flow = await pending.create("discord-link", {"user_id": who.user_id, "join": body.join})
    return {"url": discord.authorize_url(flow, body.join, _callback_uri())}


@router.get("/callback")
async def callback(
    state: str = "",
    code: str = "",
    error: str = "",
    pending: PendingStore = Depends(get_pending),
    credentials: CredentialStore = Depends(get_credentials),
):
    """Discord sends the browser here after the consent screen."""
    flow = await pending.take(state, "discord-link") if state else None
    if flow is None:
        return _back("expired")
    if error or not code:
        return _back("denied")
    try:
        linked = await discord.link(code, _callback_uri(), bool(flow.data["join"]))
    except discord.DiscordError as e:
        log.warning("discord link: %s", e)
        return _back("error")
    try:
        await credentials.link_discord(flow.data["user_id"], linked.discord_id)
    except DiscordTaken:
        return _back("taken")
    return _back("joined" if linked.joined else "linked")


@router.delete("")
async def unlink(
    who: Caller = Depends(caller), credentials: CredentialStore = Depends(get_credentials)
) -> dict:
    """Forget the Discord user, and stop the digest that went to it."""
    if await credentials.identity(who.user_id) is None:
        raise HTTPException(404, "no credentials for this identity")
    await credentials.unlink_discord(who.user_id)
    return {"linked": False, "digest": False}
