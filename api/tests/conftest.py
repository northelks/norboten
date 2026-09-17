import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from norboten.questions import providers
from norboten_api.main import create_app
from norboten_api.settings import settings


class FakeProvider(providers.Provider):
    """A vendor whose answers the test decides. Keyed by schema name, or a callable."""

    def __init__(self, name: str = "fake"):
        self.name = name
        self.answers: dict[str, object] = {}
        self.calls: list[dict] = []
        self.enabled = True

    def available(self, config) -> bool:
        return self.enabled

    def ask(self, *, model, system, user, schema, max_tokens, config):
        self.calls.append({"model": model, "system": system, "user": user, "schema": schema})
        answer = self.answers.get(schema.__name__)
        if callable(answer):
            answer = answer(model=model, user=user, schema=schema)
        if answer is None:
            raise providers.ProviderError(f"no fake answer for {schema.__name__}")
        if isinstance(answer, BaseModel):
            return answer
        return schema.model_validate(answer)


@pytest.fixture(autouse=True)
def fake_vendors(monkeypatch):
    """The server's one vendor, Ollama, is a fake; no test can reach a real model."""
    settings.cache_clear()
    monkeypatch.setenv("NORBOTEN_CONSULTANT_MODELS", "ollama/consultant")
    monkeypatch.setenv("NORBOTEN_DATABASE_URL", "memory://")
    for name in ("GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET", "DISCORD_BOT_TOKEN"):
        monkeypatch.delenv(f"NORBOTEN_{name}", raising=False)  # no test reaches GitHub or Discord
    saved = dict(providers._PROVIDERS)
    fakes = {providers.OLLAMA: FakeProvider(providers.OLLAMA)}
    for vendor, fake in fakes.items():
        providers.register(vendor, fake)
    yield fakes
    providers._PROVIDERS.clear()
    providers._PROVIDERS.update(saved)
    settings.cache_clear()


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def github(monkeypatch):
    """GitHub, answered in-process by the stub; a server with an OAuth app configured."""
    import httpx
    from oauth_stubs import GitHubState, github_stub

    from norboten_api import github as github_module

    state = GitHubState()
    monkeypatch.setenv("NORBOTEN_GITHUB_CLIENT_ID", "Iv1.stub")
    monkeypatch.setenv("NORBOTEN_GITHUB_CLIENT_SECRET", "stub-secret")
    monkeypatch.setenv("NORBOTEN_GITHUB_URL", "http://github.stub")
    monkeypatch.setenv("NORBOTEN_GITHUB_API_URL", "http://github.stub")
    settings.cache_clear()
    monkeypatch.setattr(github_module, "transport", httpx.ASGITransport(github_stub(state)))
    return state


@pytest.fixture
def discord(monkeypatch):
    """Discord, answered in-process by the stub; a server with the app and the bot configured."""
    import httpx
    from oauth_stubs import DiscordState, discord_stub

    from norboten_api import discord as discord_module

    state = DiscordState()
    monkeypatch.setenv("NORBOTEN_DISCORD_CLIENT_ID", "discord-app")
    monkeypatch.setenv("NORBOTEN_DISCORD_CLIENT_SECRET", "discord-secret")
    monkeypatch.setenv("NORBOTEN_DISCORD_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("NORBOTEN_DISCORD_GUILD_ID", "999")
    monkeypatch.setenv("NORBOTEN_DISCORD_API_URL", "http://discord.stub/api/v10")
    monkeypatch.setenv("NORBOTEN_DISCORD_AUTHORIZE_URL", "http://discord.stub/oauth2/authorize")
    settings.cache_clear()
    monkeypatch.setattr(discord_module, "transport", httpx.ASGITransport(discord_stub(state)))
    return state


@pytest.fixture
def sign_in(client, github):
    """Sign in the way a terminal does: start the device flow, GitHub approves, one poll. Returns
    what the poll answered. `github_id` and `login` say who GitHub reports."""

    def go(login: str = "tux", github_id: int | None = None, remember: bool = True, **extra):
        github.user = {"id": github_id or 1000 + sum(map(ord, login)), "login": login}
        github.device_answers = ["token"]
        github.polls = 0
        started = client.post("/auth/github/device", json={"label": "a laptop"} | extra)
        assert started.status_code == 200, started.text
        got = client.post(
            "/auth/github/poll", json={"poll_id": started.json()["poll_id"], "remember": remember}
        )
        assert got.status_code == 200, got.text
        return got.json()

    return go
