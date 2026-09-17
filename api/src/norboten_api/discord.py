"""Discord, as this server uses it: to link an account, and to send the weekly digest as a DM.

Linking is Discord's OAuth2 code flow with the `identify` scope, plus `guilds.join` only when the
learner ticked "join the Norboten server" (off by default). The access token is used for
`GET /users/@me`, and for `PUT /guilds/{guild}/members/{user}` when joining, and is then dropped —
nothing of Discord's is stored but the user id.

The digest goes through the REST API with the bot token, no gateway connection: open a DM channel
(`POST /users/@me/channels`), post the message. A DM needs the bot and the person to share a server,
which is what joining gives. Error `50007` means Discord will not take messages from the bot for
that person — DMs closed, or no shared server — and is recorded for the account page; a 429 waits
`retry_after` and tries again.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from norboten_api.settings import settings

TIMEOUT = 15
#: Discord's error code for "Cannot send messages to this user".
CANNOT_DM = 50007
#: A message longer than this is refused by Discord.
MAX_MESSAGE = 2000

#: Set by tests to answer Discord in-process; None is the network.
transport: httpx.AsyncBaseTransport | None = None

CANNOT_DM_TEXT = (
    "Discord will not take messages from the Norboten bot for you: allow direct messages from "
    "members of the Norboten server, and make sure you are in it."
)


class DiscordError(RuntimeError):
    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Linked:
    discord_id: str
    joined: bool


def configured() -> bool:
    """Linking needs the OAuth2 app; the digest needs the bot. Both, or Discord is off."""
    config = settings()
    return bool(
        config.discord_client_id and config.discord_client_secret and config.discord_bot_token
    )


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, transport=transport)


def _api(path: str) -> str:
    return f"{settings().discord_api_url.rstrip('/')}{path}"


def authorize_url(state: str, join: bool, redirect_uri: str) -> str:
    scope = "identify guilds.join" if join else "identify"
    query = httpx.QueryParams(
        {
            "client_id": settings().discord_client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
            "prompt": "consent",
        }
    )
    return f"{settings().discord_authorize_url}?{query}"


async def link(code: str, redirect_uri: str, join: bool) -> Linked:
    """The code from Discord's redirect: who this is, and the Norboten server joined if asked."""
    config = settings()
    try:
        async with _client() as client:
            token = await client.post(
                _api("/oauth2/token"),
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                auth=(config.discord_client_id, config.discord_client_secret),
            )
            if token.status_code != 200:
                raise DiscordError(f"Discord refused the code (HTTP {token.status_code})")
            access = token.json()["access_token"]
            me = await client.get(_api("/users/@me"), headers={"Authorization": f"Bearer {access}"})
            if me.status_code != 200:
                raise DiscordError(f"Discord would not say who this is (HTTP {me.status_code})")
            discord_id = str(me.json()["id"])
            joined = False
            if join and config.discord_guild_id:
                put = await client.put(
                    _api(f"/guilds/{config.discord_guild_id}/members/{discord_id}"),
                    json={"access_token": access},
                    headers={"Authorization": f"Bot {config.discord_bot_token}"},
                )
                joined = put.status_code in (201, 204)
    except httpx.HTTPError as e:
        raise DiscordError(f"Discord did not answer ({type(e).__name__})") from e
    return Linked(discord_id, joined)


async def send_dm(discord_id: str, content: str, tries: int = 3) -> None:
    """One direct message from the bot. Raises `DiscordError` (with Discord's code) when it cannot
    be delivered; a rate limit is waited out, up to `tries` times."""
    content = content if len(content) <= MAX_MESSAGE else content[: MAX_MESSAGE - 1] + "…"
    async with _client() as client:
        channel = await _post(client, "/users/@me/channels", {"recipient_id": discord_id}, tries)
        await _post(client, f"/channels/{channel['id']}/messages", {"content": content}, tries)


async def _post(client: httpx.AsyncClient, path: str, payload: dict, tries: int) -> dict:
    headers = {"Authorization": f"Bot {settings().discord_bot_token}"}
    for attempt in range(tries):
        try:
            answer = await client.post(_api(path), json=payload, headers=headers)
        except httpx.HTTPError as e:
            raise DiscordError(f"Discord did not answer ({type(e).__name__})") from e
        if answer.status_code == 429 and attempt < tries - 1:
            await asyncio.sleep(float(_json(answer).get("retry_after", 1)))
            continue
        body = _json(answer)
        if answer.status_code >= 400:
            raise DiscordError(
                body.get("message", f"HTTP {answer.status_code}"), int(body.get("code", 0))
            )
        return body
    raise DiscordError("Discord kept rate-limiting the bot")  # unreachable: the last try returns


def _json(answer: httpx.Response) -> dict:
    try:
        body = answer.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}
