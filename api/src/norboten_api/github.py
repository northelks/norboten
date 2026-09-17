"""GitHub, as this server uses it: to learn who someone is, once, and forget the token at once.

Two ways to that one fact. The **device flow** (a terminal: `POST /login/device/code`, then the
token endpoint polled with the device grant) and the **web flow** (the site:
`/login/oauth/authorize`, then the code exchanged with the client secret). Either ends in a GitHub
token that is used for one `GET /user` — the numeric `id`, which never changes, and the `login`,
which can — and is then revoked (`DELETE /applications/{client_id}/token`). No scope is asked for,
so the token could read nothing private even while it existed, and no GitHub token is stored
anywhere.

The URLs are settings, so the tests and a rehearsal point them at a stub; `transport` is for the
tests that run the stub in-process.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from norboten_api.settings import settings

TIMEOUT = 15
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"

#: Set by tests to answer GitHub's endpoints in-process; None is the network.
transport: httpx.AsyncBaseTransport | None = None


class GitHubError(RuntimeError):
    """GitHub did not answer, or answered something this server cannot use."""


class NotConfigured(GitHubError):
    """No OAuth app on this deployment: nobody can sign in."""


@dataclass(frozen=True)
class Identity:
    github_id: int
    login: str


def configured() -> bool:
    config = settings()
    return bool(config.github_client_id and config.github_client_secret)


def _require() -> None:
    if not configured():
        raise NotConfigured("sign-in is not configured on this server")


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, transport=transport)


async def _form(path: str, data: dict) -> dict:
    url = f"{settings().github_url.rstrip('/')}{path}"
    try:
        async with _client() as client:
            answer = await client.post(url, data=data, headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        raise GitHubError(f"GitHub did not answer ({type(e).__name__})") from e
    if answer.status_code >= 500:
        raise GitHubError(f"GitHub answered HTTP {answer.status_code}")
    try:
        return answer.json()
    except ValueError as e:
        raise GitHubError("GitHub answered something that is not JSON") from e


async def device_code() -> dict:
    """A device code and the user code a person types at github.com/login/device."""
    _require()
    body = await _form("/login/device/code", {"client_id": settings().github_client_id})
    if "device_code" not in body:
        # "device_flow_disabled" is the usual one: the OAuth app needs Enable Device Flow ticked
        raise GitHubError(f"GitHub refused a device code: {body.get('error', 'no reason given')}")
    return body


async def poll(device: str) -> dict:
    """One poll of the token endpoint: `{"access_token": …}` or `{"error": …}` as GitHub says it."""
    _require()
    return await _form(
        "/login/oauth/access_token",
        {
            "client_id": settings().github_client_id,
            "device_code": device,
            "grant_type": DEVICE_GRANT,
        },
    )


async def exchange(code: str, redirect_uri: str) -> str:
    """The web flow's code, for a token. Raises when GitHub refuses it."""
    _require()
    config = settings()
    body = await _form(
        "/login/oauth/access_token",
        {
            "client_id": config.github_client_id,
            "client_secret": config.github_client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
    )
    if not body.get("access_token"):
        raise GitHubError(f"GitHub refused the code: {body.get('error', 'no reason given')}")
    return body["access_token"]


def authorize_url(state: str, redirect_uri: str) -> str:
    """Where the browser goes to approve this app. No scope: only the public identity."""
    query = httpx.QueryParams(
        {"client_id": settings().github_client_id, "redirect_uri": redirect_uri, "state": state}
    )
    return f"{settings().github_url.rstrip('/')}/login/oauth/authorize?{query}"


async def identify(token: str) -> Identity:
    """Who the token belongs to — then the token is revoked, whatever happened in between."""
    config = settings()
    try:
        async with _client() as client:
            answer = await client.get(
                f"{config.github_api_url.rstrip('/')}/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
            )
    except httpx.HTTPError as e:
        raise GitHubError(f"GitHub did not answer ({type(e).__name__})") from e
    finally:
        await revoke(token)
    if answer.status_code != 200:
        raise GitHubError(f"GitHub would not say who this is (HTTP {answer.status_code})")
    user = answer.json()
    return Identity(github_id=int(user["id"]), login=str(user["login"]))


async def revoke(token: str) -> None:
    """Best effort: an unrevoked token with no scope still expires unused, and sign-in goes on."""
    config = settings()
    try:
        async with _client() as client:
            await client.request(
                "DELETE",
                f"{config.github_api_url.rstrip('/')}/applications/{config.github_client_id}/token",
                json={"access_token": token},
                auth=(config.github_client_id, config.github_client_secret),
                headers={"Accept": "application/vnd.github+json"},
            )
    except httpx.HTTPError:
        return
