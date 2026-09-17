"""GitHub and Discord, as far as this server talks to them — stubs whose answers a test decides.

Each is a small FastAPI app with its state on it. A test mounts one in-process
(`github.transport = httpx.ASGITransport(stub)`); a rehearsal or the site's Chrome drive serves one
with uvicorn and points `NORBOTEN_GITHUB_URL` / `NORBOTEN_GITHUB_API_URL` / `NORBOTEN_DISCORD_*` at
it:

    uv run python api/tests/oauth_stubs.py 8119      # GitHub and Discord on one port

Their shapes follow the real APIs: GitHub's device flow and token endpoint answer 200 with an
`error` field, as GitHub does; Discord's errors carry a numeric `code`.
"""

from __future__ import annotations

import itertools
import sys
from dataclasses import dataclass, field

from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

USER_CODE = "WDJB-MJHT"


@dataclass
class GitHubState:
    #: Who approves: the account GitHub reports for the next token.
    user: dict = field(default_factory=lambda: {"id": 1001, "login": "Tux-Penguin"})
    #: What the device polls answer, in order; the last one repeats. "token" means approved.
    device_answers: list[str] = field(default_factory=lambda: ["token"])
    tokens: dict[str, dict] = field(default_factory=dict)
    codes: dict[str, dict] = field(default_factory=dict)
    revoked: list[str] = field(default_factory=list)
    polls: int = 0
    counter: itertools.count = field(default_factory=lambda: itertools.count(1))

    def issue(self) -> str:
        token = f"gho_stub{next(self.counter)}"
        self.tokens[token] = dict(self.user)
        return token


def github_stub(state: GitHubState | None = None) -> FastAPI:
    app = FastAPI()
    app.state.gh = gh = state or GitHubState()

    @app.post("/login/device/code")
    async def device_code(client_id: str = Form()):
        return {
            "device_code": f"dev-{next(gh.counter)}",
            "user_code": USER_CODE,
            "verification_uri": "https://github.com/login/device",
            "expires_in": 900,
            "interval": 5,
        }

    @app.post("/login/oauth/access_token")
    async def access_token(request: Request):
        form = await request.form()
        if form.get("grant_type") == "urn:ietf:params:oauth:grant-type:device_code":
            answer = gh.device_answers[min(gh.polls, len(gh.device_answers) - 1)]
            gh.polls += 1
            if answer == "token":
                return {"access_token": gh.issue(), "token_type": "bearer", "scope": ""}
            if answer == "slow_down":
                return {"error": "slow_down", "interval": 10}
            return {"error": answer}
        code = form.get("code", "")
        if code not in gh.codes or not form.get("client_secret"):
            return {"error": "bad_verification_code"}
        gh.codes.pop(code)
        return {"access_token": gh.issue(), "token_type": "bearer", "scope": ""}

    @app.get("/login/oauth/authorize")
    async def authorize(redirect_uri: str, state: str, client_id: str = ""):
        # the person clicks Authorize at once
        code = f"code-{next(gh.counter)}"
        gh.codes[code] = dict(gh.user)
        return RedirectResponse(f"{redirect_uri}?code={code}&state={state}", 302)

    @app.get("/user")
    async def user(request: Request):
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if token not in gh.tokens or token in gh.revoked:
            return JSONResponse({"message": "Bad credentials"}, status_code=401)
        return gh.tokens[token]

    @app.delete("/applications/{client_id}/token")
    async def revoke(client_id: str, request: Request):
        gh.revoked.append((await request.json())["access_token"])
        return Response(status_code=204)

    return app


@dataclass
class DiscordState:
    user_id: str = "80351110224678912"
    #: Recipients whose DMs are closed (50007), and ones rate-limited once before they work.
    closed: set[str] = field(default_factory=set)
    rate_limited_once: set[str] = field(default_factory=set)
    joined: list[tuple[str, str]] = field(default_factory=list)
    messages: list[tuple[str, str]] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)


def discord_stub(state: DiscordState | None = None) -> FastAPI:
    app = FastAPI()
    app.state.dc = dc = state or DiscordState()

    @app.get("/oauth2/authorize")
    async def authorize(redirect_uri: str, state: str, scope: str = "", client_id: str = ""):
        dc.scopes.append(scope)
        return RedirectResponse(f"{redirect_uri}?code=discord-code&state={state}", 302)

    @app.post("/api/v10/oauth2/token")
    async def token(code: str = Form(), grant_type: str = Form(), redirect_uri: str = Form("")):
        if code != "discord-code":
            return JSONResponse({"error": "invalid_grant"}, status_code=400)
        return {"access_token": "discord-access", "token_type": "Bearer", "scope": "identify"}

    @app.get("/api/v10/users/@me")
    async def me(request: Request):
        if request.headers.get("authorization") != "Bearer discord-access":
            return JSONResponse({"message": "401: Unauthorized", "code": 0}, status_code=401)
        return {"id": dc.user_id, "username": "tux"}

    @app.put("/api/v10/guilds/{guild}/members/{user}")
    async def join(guild: str, user: str):
        dc.joined.append((guild, user))
        return Response(status_code=201)

    @app.post("/api/v10/users/@me/channels")
    async def channel(request: Request):
        recipient = (await request.json())["recipient_id"]
        if recipient in dc.rate_limited_once:
            dc.rate_limited_once.discard(recipient)
            return JSONResponse(
                {"message": "You are being rate limited.", "retry_after": 0.01, "global": False},
                status_code=429,
            )
        return {"id": f"dm-{recipient}", "type": 1}

    @app.post("/api/v10/channels/{channel_id}/messages")
    async def message(channel_id: str, request: Request):
        recipient = channel_id.removeprefix("dm-")
        if recipient in dc.closed:
            return JSONResponse(
                {"message": "Cannot send messages to this user", "code": 50007}, status_code=403
            )
        dc.messages.append((recipient, (await request.json())["content"]))
        return {"id": "1", "channel_id": channel_id}

    return app


def both() -> FastAPI:
    """GitHub at `/github`, its API at `/github-api`, Discord at `/discord` — one port to serve."""
    app = FastAPI()
    gh = github_stub()
    app.mount("/github-api", gh)
    app.mount("/github", gh)
    app.mount("/discord", discord_stub())
    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(both(), port=int(sys.argv[1]) if len(sys.argv) > 1 else 8119)
