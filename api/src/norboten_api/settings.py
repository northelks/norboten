"""Configuration, from the environment. No secret ever reaches a client."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NORBOTEN_", extra="ignore")

    #: postgresql://user:password@host/db for the server; memory:// for tests and a laptop.
    database_url: str = "memory://"
    #: redis://host:6379/0 for live frames, rate limits and the board cache;
    #: empty keeps them in this process, which is only right with a single worker.
    redis_url: str = ""
    #: Questions one client may ask the consultant per minute.
    chat_per_minute: int = 20

    #: Ollama on the same server (the compose service `ollama`); empty means none. It is the only
    #: model provider the server uses: no hosted model key is read, so none can be billed.
    ollama_url: str = ""
    #: The consultant tries these in order and uses the first this server can reach.
    consultant_models: str = "ollama/qwen2.5:0.5b"

    #: Browser origins allowed to call this API. The site is served from another origin, so it
    #: has to be listed; a self-hosted deployment lists its own.
    allowed_origins: str = "https://norboten.org,https://www.norboten.org"

    telemetry_enabled: bool = True  # the server accepts it; the CLI never sends it unasked

    #: Stripe's secret key (`sk_live_…`, or `sk_test_…` to rehearse). Empty: the donate page says
    #: card donations are off on this deployment and offers the other ways to help.
    stripe_secret_key: str = ""
    stripe_api_url: str = "https://api.stripe.com"
    #: Checkout Sessions one client may start per minute.
    donations_per_minute: int = 6

    #: The site, for the links the API hands out (the account page, the MCP consent page).
    site_url: str = "https://norboten.org"
    #: This API's own public address. The OAuth issuer is this URL and the MCP server's resource
    #: identifier is `<api_url>/mcp`, so it must be what clients reach, scheme and host exact.
    api_url: str = "https://api.norboten.org"
    #: MCP requests one client may make per minute.
    mcp_per_minute: int = 120
    #: Seals the state an MCP question carries between its two requests; every worker needs the
    #: same one. Empty: a key per process, which is right only with a single worker.
    mcp_state_key: str = ""
    #: The rated labs and banks, mounted read-only beside the container — never built into the
    #: image. Empty, missing or bare: this server has no rated content (docs/rated-labs.md).
    rated_dir: str = ""
    #: Rated attempts one client may start per minute.
    rated_per_minute: int = 10
    #: On the server: a request must carry a token this server issued. Off, X-Debug-User works.
    require_auth: bool = False

    #: The GitHub OAuth App everyone signs in with (Settings → Developer settings → OAuth Apps,
    #: with Enable Device Flow ticked). **Empty means nobody can sign in**: the sign-in endpoints
    #: answer 503, because GitHub is the only way in. Its one callback URL is
    #: `<api_url>/auth/github/callback`.
    github_client_id: str = ""
    github_client_secret: str = ""
    #: GitHub's two hosts; a test or a rehearsal points them at a stub.
    github_url: str = "https://github.com"
    github_api_url: str = "https://api.github.com"
    #: Sign-ins one client may start per minute.
    sign_ins_per_minute: int = 10

    #: Discord, optional: linking an account, and the weekly digest as a direct message from the
    #: bot. Empty client id or bot token: the account page hides Discord and no digest is sent.
    #: The OAuth2 redirect is `<api_url>/auth/discord/callback`.
    discord_client_id: str = ""
    discord_client_secret: str = ""
    discord_bot_token: str = ""
    #: The Norboten server a linked account may join, and the bot shares with its members — a bot
    #: can only send a direct message to someone it shares a server with.
    discord_guild_id: str = ""
    discord_api_url: str = "https://discord.com/api/v10"
    discord_authorize_url: str = "https://discord.com/oauth2/authorize"

    #: The offline country table `GET /geo/country` searches (`geo.py`), compiled from DB-IP Lite
    #: at image build. Missing: every guess is empty, and the country field simply starts blank.
    geo_db: str = "/app/geo/country.bin"

    #: Where a real session going live is announced (`announce.py`). Empty sends nothing.
    telegram_bot_token: str = ""
    telegram_chat: str = ""
    telegram_api_url: str = "https://api.telegram.org"

    @property
    def allowed_origin_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def consultant_list(self) -> list[str]:
        return [m.strip() for m in self.consultant_models.split(",") if m.strip()]


@lru_cache
def settings() -> Settings:
    return Settings()
