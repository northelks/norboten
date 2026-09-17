"""Signing in: with GitHub, and nothing else.

There is no password on this server and no email address. GitHub is asked one question — who is
this? — and the answer is its numeric user id; the GitHub token that carried the answer is revoked
at once and stored nowhere (`github.py`). The first sign-in creates the account.

**A terminal** uses GitHub's device flow, proxied here so that no GitHub token ever reaches the
learner's machine, and so that this server never has to trust a token some other app obtained:

1. `POST /auth/github/device` `{label, remember}` — GitHub issues a device code, kept here
   (`pending.py`); the terminal gets only `{poll_id, user_code, verification_uri, interval}`;
2. the person types `user_code` at `verification_uri`, on any device;
3. `POST /auth/github/poll` `{poll_id}` — one call to GitHub per poll: 428 while GitHub is still
   waiting, 429 with a longer `interval` when it says slow down, 410 once the code expired, 403
   when it was denied, and a `cli` token when it was approved.

**The site** uses the web flow:

1. `GET /auth/github/go?state=…&remember=…&return=account|authorize:<request>` — the page's own
   random `state` is kept here, and the browser is sent to GitHub with this server's state;
2. `GET /auth/github/callback` — the code is exchanged with the client secret, and the browser is
   sent back to the page with `#once=<code>&state=<its state>` in the fragment: never a token in a
   URL, and a fragment is not sent to any server;
3. `POST /auth/github/exchange` `{once}` — after the page has checked `state` against what it
   stored (login CSRF), the one-time code — sixty seconds, one use — becomes a `web` token.

`remember` is the whole of "remember me": ninety days when on, twelve hours when off. There are no
cookies and no server-side session. Without an OAuth app configured every sign-in endpoint answers
503 "sign-in is not configured on this server".
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from norboten_api import discord, github, live
from norboten_api.auth import Caller, caller, get_credentials, get_pending
from norboten_api.credentials import CredentialStore, new_token
from norboten_api.deps import client_key, get_bus
from norboten_api.live import Bus
from norboten_api.pending import ONCE_SECONDS, PendingStore
from norboten_api.settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])

log = logging.getLogger("norboten_api.auth")

#: A remembered browser or terminal.
REMEMBERED_SECONDS = 90 * 24 * 3600
#: Not remembered: long enough for one sitting, short enough to leave on a shared machine.
SESSION_SECONDS = 12 * 3600

#: Where the site may ask to be sent back to: its account page, or an MCP client's pending request.
RETURN = re.compile(r"^(account|authorize:[A-Za-z0-9_-]{8,128})$")


class DeviceIn(BaseModel):
    #: Which terminal is asking, shown in the list of signed-in machines.
    label: str = Field(default="a terminal", min_length=1, max_length=120)
    remember: bool = False


class PollIn(BaseModel):
    poll_id: str = Field(min_length=8, max_length=128)
    #: Decided when the sign-in finishes, so the box can still change while GitHub waits.
    remember: bool | None = None


class ExchangeIn(BaseModel):
    once: str = Field(min_length=8, max_length=128)


class PreferencesIn(BaseModel):
    digest: bool  # the weekly note about this account's own week, as a Discord direct message


def _not_configured() -> HTTPException:
    return HTTPException(503, "sign-in is not configured on this server")


async def _limit(request: Request, bus: Bus, bucket: str) -> None:
    if await live.limited(bus, bucket, client_key(request), settings().sign_ins_per_minute):
        raise HTTPException(429, "too many sign-ins from here; wait a minute")


async def _issue(
    credentials: CredentialStore, who: github.Identity, kind: str, remember: bool, label: str
) -> dict:
    user_id, created = await credentials.ensure_github(who.github_id, who.login)
    seconds = REMEMBERED_SECONDS if remember else SESSION_SECONDS
    token = new_token()
    await credentials.add_token(token, user_id, kind, seconds, label=label)
    return {
        "token": token,
        "access_token": token,  # the TUI's name for it, as OAuth spells it
        "token_type": "bearer",
        "user_id": user_id,
        "github_login": who.login,
        "expires_in": seconds,
        "new_account": created,
    }


@router.get("/config")
async def config() -> dict:
    """How to sign in on this server. The TUI and the site ask, so a self-hosted server needs no
    new release; `discord` says whether the account page offers linking Discord."""
    site = settings().site_url.rstrip("/")
    return {
        "mode": "github",
        "github": github.configured(),
        "discord": discord.configured(),
        "account_uri": f"{site}/account/",
    }


# -- a terminal: the device flow -----------------------------------------------------------------


@router.post("/github/device")
async def device(
    body: DeviceIn,
    request: Request,
    pending: PendingStore = Depends(get_pending),
    bus: Bus = Depends(get_bus),
) -> dict:
    """Start signing a terminal in. GitHub's device code stays here; the terminal gets the code a
    person types, the page to type it on, and a handle to poll with."""
    if not github.configured():
        raise _not_configured()
    await _limit(request, bus, "sign-in-device")
    try:
        answer = await github.device_code()
    except github.GitHubError as e:
        log.warning("device code: %s", e)
        raise HTTPException(502, "GitHub would not start a sign-in; try again shortly") from e
    ttl = min(int(answer.get("expires_in", 900)), 900)
    poll_id = await pending.create(
        "device",
        {
            "device_code": answer["device_code"],
            "interval": int(answer.get("interval", 5)),
            "label": body.label,
            "remember": body.remember,
        },
        ttl=ttl,
    )
    return {
        "poll_id": poll_id,
        "user_code": answer["user_code"],
        "verification_uri": answer.get("verification_uri", "https://github.com/login/device"),
        "interval": int(answer.get("interval", 5)),
        "expires_in": ttl,
    }


@router.post("/github/poll")
async def poll(
    body: PollIn,
    request: Request,
    pending: PendingStore = Depends(get_pending),
    credentials: CredentialStore = Depends(get_credentials),
):
    """Has the person approved on GitHub yet? One call to GitHub per poll, so a terminal that polls
    faster than `interval` is told to slow down by GitHub itself."""
    if not github.configured():
        raise _not_configured()
    flow = await pending.get(body.poll_id, "device")
    if flow is None:
        raise HTTPException(410, "this sign-in has expired; start again")
    try:
        answer = await github.poll(flow.data["device_code"])
    except github.GitHubError as e:
        log.warning("device poll: %s", e)
        raise HTTPException(502, "GitHub did not answer; try again shortly") from e

    error = answer.get("error")
    if error == "authorization_pending":
        return JSONResponse(
            {"detail": "waiting for GitHub", "interval": flow.data["interval"]}, status_code=428
        )
    if error == "slow_down":
        interval = int(answer.get("interval") or flow.data["interval"] + 5)
        await pending.update(flow.id, flow.data | {"interval": interval})
        return JSONResponse(
            {"detail": "polling too fast; slow down", "interval": interval}, status_code=429
        )
    if error == "expired_token":
        await pending.take(flow.id, "device")
        raise HTTPException(410, "the code expired before it was approved; start again")
    if error == "access_denied":
        await pending.take(flow.id, "device")
        raise HTTPException(403, "denied on GitHub")
    if error or not answer.get("access_token"):
        await pending.take(flow.id, "device")
        log.warning("device poll: GitHub said %s", error)
        raise HTTPException(502, "GitHub refused this sign-in; start again")

    if await pending.take(flow.id, "device") is None:
        raise HTTPException(410, "this sign-in was already used; start again")
    try:
        who = await github.identify(answer["access_token"])
    except github.GitHubError as e:
        log.warning("device identify: %s", e)
        raise HTTPException(502, "GitHub would not say who you are; start again") from e
    remember = flow.data["remember"] if body.remember is None else body.remember
    return await _issue(credentials, who, "cli", remember, flow.data["label"])


# -- the site: the web flow ----------------------------------------------------------------------


def _callback_uri() -> str:
    return f"{settings().api_url.rstrip('/')}/auth/github/callback"


def _page(target: str) -> str:
    site = settings().site_url.rstrip("/")
    if target.startswith("authorize:"):
        return f"{site}/authorize/?request={target.split(':', 1)[1]}"
    return f"{site}/account/"


@router.get("/github/go")
async def go(
    request: Request,
    state: str = Query(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
    remember: bool = False,
    return_to: str = Query(default="account", alias="return"),
    pending: PendingStore = Depends(get_pending),
    bus: Bus = Depends(get_bus),
):
    """Send the browser to GitHub. The page's `state` comes back to it in the fragment; GitHub is
    given this server's own state, which names the flow."""
    if not RETURN.match(return_to):
        raise HTTPException(422, "return must be account or authorize:<request>")
    if not github.configured():
        return RedirectResponse(f"{_page(return_to)}#error=not-configured", 302)
    await _limit(request, bus, "sign-in-web")
    flow_id = await pending.create(
        "web", {"state": state, "remember": remember, "return": return_to}
    )
    return RedirectResponse(github.authorize_url(flow_id, _callback_uri()), 302)


@router.get("/github/callback")
async def callback(
    state: str = "",
    code: str = "",
    error: str = "",
    pending: PendingStore = Depends(get_pending),
):
    """GitHub sends the browser here. Whatever happens, the browser goes back to the page it came
    from, with a one-time code or an error in the fragment."""
    flow = await pending.take(state, "web") if state else None
    if flow is None:
        return RedirectResponse(f"{_page('account')}#error=expired", 302)
    back = _page(flow.data["return"])
    if error or not code:
        reason = "denied" if error == "access_denied" else "github"
        return RedirectResponse(f"{back}#error={reason}", 302)
    try:
        token = await github.exchange(code, _callback_uri())
        who = await github.identify(token)
    except github.GitHubError as e:
        log.warning("web sign-in: %s", e)
        return RedirectResponse(f"{back}#error=github", 302)
    once = await pending.create(
        "once",
        {"github_id": who.github_id, "login": who.login, "remember": flow.data["remember"]},
        ttl=ONCE_SECONDS,
    )
    return RedirectResponse(f"{back}#once={once}&state={flow.data['state']}", 302)


@router.post("/github/exchange")
async def exchange(
    body: ExchangeIn,
    request: Request,
    pending: PendingStore = Depends(get_pending),
    credentials: CredentialStore = Depends(get_credentials),
    bus: Bus = Depends(get_bus),
) -> dict:
    """The one-time code from the callback, for a `web` token. It works once, for sixty seconds."""
    await _limit(request, bus, "sign-in-exchange")
    found = await pending.take(body.once, "once")
    if found is None:
        raise HTTPException(410, "this sign-in link has expired or was already used; sign in again")
    who = github.Identity(found.data["github_id"], found.data["login"])
    return await _issue(credentials, who, "web", bool(found.data["remember"]), "site")


# -- the signed-in account -----------------------------------------------------------------------


@router.post("/logout")
async def logout(
    who: Caller = Depends(caller), credentials: CredentialStore = Depends(get_credentials)
) -> dict:
    """Revoke the token this request was made with."""
    if who.token:
        await credentials.revoke(who.token)
    return {"signed_out": True}


@router.get("/tokens")
async def tokens(
    who: Caller = Depends(caller), credentials: CredentialStore = Depends(get_credentials)
) -> list[dict]:
    """Where this account is signed in: the site and each terminal, with when each expires."""
    return await credentials.tokens(who.user_id)


@router.get("/me")
async def identity(
    who: Caller = Depends(caller), credentials: CredentialStore = Depends(get_credentials)
) -> dict:
    """Who this account is on GitHub, and what it has linked and asked for — for its own account
    page. 404 for a debug identity, which has no credentials."""
    found = await credentials.identity(who.user_id)
    if found is None:
        raise HTTPException(404, "no credentials for this identity")
    return {
        "github_login": found.github_login,
        "github_id": found.github_id,
        "discord": {
            "available": discord.configured(),
            "linked": found.discord_id is not None,
            "error": found.discord_error,
            "invite": settings().discord_guild_id != "",
        },
        "digest": found.digest,
    }


@router.get("/preferences")
async def preferences(
    who: Caller = Depends(caller), credentials: CredentialStore = Depends(get_credentials)
) -> dict:
    """What this account has asked to be sent. Everything is off until the learner turns it on."""
    found = await credentials.identity(who.user_id)
    return {"digest": bool(found and found.digest)}


@router.put("/preferences")
async def set_preferences(
    body: PreferencesIn,
    who: Caller = Depends(caller),
    credentials: CredentialStore = Depends(get_credentials),
) -> dict:
    """Turn the weekly digest on or off. It is a Discord direct message, so it can only be turned on
    once Discord is linked (409 before that)."""
    found = await credentials.identity(who.user_id)
    if found is None:
        raise HTTPException(404, "no credentials for this identity")
    if body.digest and found.discord_id is None:
        raise HTTPException(409, "link Discord first: the digest is a Discord direct message")
    await credentials.set_digest(who.user_id, body.digest)
    return {"digest": body.digest}
