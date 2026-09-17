"""Who is calling: a bearer token this server issued, looked up by its hash.

No password anywhere. An account is a GitHub account (`credentials.py`); signing in on GitHub issues
a `web` token on the site or a `cli` token in a terminal (`routers/auth.py`). Either arrives as
`Authorization: Bearer <token>` and becomes a `user_id` here — a client never sends an id of its
own.

With `require_auth` off (tests, a laptop) a request with no token may instead name itself with
`X-Debug-User`. The server deployment turns that off, and then a missing token is a 401.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request

from norboten_api.account_store import AccountStore
from norboten_api.accounts import User
from norboten_api.credentials import CredentialStore
from norboten_api.pending import PendingStore
from norboten_api.settings import settings


class Caller:
    """An authenticated identity. The profile may not exist yet — signing in comes first."""

    def __init__(self, user_id: str, token: str = "", dev: bool = False) -> None:
        self.user_id = user_id
        self.token = token
        self.dev = dev


def get_accounts(request: Request) -> AccountStore:
    return request.app.state.accounts


def get_credentials(request: Request) -> CredentialStore:
    return request.app.state.credentials


def get_pending(request: Request) -> PendingStore:
    return request.app.state.pending


async def caller(
    authorization: str = Header(default=""),
    x_debug_user: str = Header(default=""),
    credentials: CredentialStore = Depends(get_credentials),
) -> Caller:
    """The identity behind a request, or 401."""
    scheme, _, token = authorization.partition(" ")
    if token and scheme.lower() == "bearer":
        found = await credentials.lookup(token.strip())
        if found is None:
            raise HTTPException(401, "this token is unknown or expired; sign in again")
        if found.kind.startswith("mcp"):
            # issued for the MCP server (its audience); the rest of the API does not accept it
            raise HTTPException(401, "this token is for the MCP server only")
        return Caller(user_id=found.user_id, token=token.strip())
    if settings().require_auth or not x_debug_user:
        raise HTTPException(401, "sign in: press a in norboten, or sign in on the site")
    return Caller(user_id=x_debug_user, dev=True)


async def current_user(
    who: Caller = Depends(caller),
    accounts: AccountStore = Depends(get_accounts),
) -> User:
    """The caller's profile. 404 until they have chosen a nick."""
    user = await accounts.user(who.user_id)
    if user is None:
        raise HTTPException(404, "no profile yet: POST /me to choose a nick")
    return user
