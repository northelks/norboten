"""Telegram, told when a real session goes live: "<nick> is working on <lab> right now."

Called once per session, from `POST /play/sessions`, after the response is sent — a slow or
failing Telegram never delays or breaks the recorder. Sample recordings are never announced.
Without `NORBOTEN_TELEGRAM_BOT_TOKEN` and `NORBOTEN_TELEGRAM_CHAT` nothing is sent.

This replaced a workflow that polled `/play/live` every five minutes: the API knows the moment a
session starts, so it says so then, and nothing has to remember what it already announced.
"""

from __future__ import annotations

import logging

import httpx

from norboten_api.play_store import PlaySession
from norboten_api.settings import settings

log = logging.getLogger(__name__)


def live_text(session: PlaySession) -> str:
    site = settings().site_url.rstrip("/")
    lab = session.lab_title or session.lab_id
    return f"{session.nick} is working on {lab} right now.\n{site}/live/"


async def live_session(session: PlaySession) -> bool:
    s = settings()
    if session.seed or not (s.telegram_bot_token and s.telegram_chat):
        return False
    url = f"{s.telegram_api_url.rstrip('/')}/bot{s.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                url, json={"chat_id": s.telegram_chat, "text": live_text(session)}
            )
            r.raise_for_status()
    except httpx.HTTPError as e:
        # the token is part of the URL: log the error's kind, never the request
        log.warning("announcing live session %s failed: %s", session.session_id, type(e).__name__)
        return False
    return True
