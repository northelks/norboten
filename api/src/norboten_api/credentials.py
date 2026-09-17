"""Credentials and tokens: how an account proves who it is.

An account is a GitHub account, and nothing else — no password, no email address. Signing in on
GitHub (`routers/auth.py`, `github.py`) tells this server one fact, GitHub's numeric user id, which
never changes; the login is kept beside it, refreshed at every sign-in, because a GitHub login can
be renamed and the public profile links to it. Signing in issues an opaque token — random bytes the
client keeps — and the server stores only its SHA-256. A stolen database therefore holds no usable
token, and signing out, or revoking a terminal, is deleting a row.

Kinds of token:

* `web` — the site, after GitHub; ninety days when the browser is remembered, twelve hours when it
  is not;
* `cli` — the TUI, after GitHub's device flow; the same two lives, and one token per terminal,
  labelled with the machine that asked;
* `mcp` and `mcp-refresh` — an MCP client, after the account approved it on the site (OAuth 2.1,
  `routers/oauth.py`): an hour, and thirty days to get another. An `mcp` token is good for the MCP
  server only — its audience — and the rest of the API refuses it.

Discord is optional and separate: an account may link one Discord user (`discord_id`), and only a
linked account can turn the weekly digest on, because the digest is a Discord direct message
(`digest.py`). `discord_error` keeps what went wrong the last time a message could not be delivered,
for the account page to say.

The profile (nick, country, ratings) is separate and keyed by the same `user_id` — see
`account_store.py`. The first sign-in creates the credentials; choosing a nick creates the profile.
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass, replace
from typing import Protocol


@dataclass(frozen=True)
class TokenInfo:
    user_id: str
    kind: str
    label: str = ""


@dataclass(frozen=True)
class Identity:
    """What an account is linked to, for its owner's account page."""

    user_id: str
    github_id: int
    github_login: str
    discord_id: str | None = None
    digest: bool = False
    discord_error: str = ""


@dataclass(frozen=True)
class Subscriber:
    user_id: str
    discord_id: str


class DiscordTaken(ValueError):
    """That Discord user is already linked to another Norboten account."""


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class CredentialStore(Protocol):
    async def setup(self) -> None: ...
    async def ensure_github(self, github_id: int, login: str) -> tuple[str, bool]: ...
    async def identity(self, user_id: str) -> Identity | None: ...
    async def github_logins(self, user_ids: list[str]) -> dict[str, str]: ...
    async def add_token(
        self, token: str, user_id: str, kind: str, ttl: int, label: str = ""
    ) -> None: ...
    async def user_for(self, token: str) -> str | None: ...
    async def lookup(self, token: str) -> TokenInfo | None: ...
    async def revoke(self, token: str) -> None: ...
    async def tokens(self, user_id: str) -> list[dict]: ...
    async def link_discord(self, user_id: str, discord_id: str) -> None: ...
    async def unlink_discord(self, user_id: str) -> None: ...
    async def set_digest(self, user_id: str, on: bool) -> None: ...
    async def set_discord_error(self, user_id: str, error: str) -> None: ...
    async def digest_subscribers(self) -> list[Subscriber]: ...
    async def forget(self, user_id: str) -> None: ...
    async def close(self) -> None: ...


class MemoryCredentialStore:
    def __init__(self) -> None:
        self._accounts: dict[str, Identity] = {}
        self._tokens: dict[str, dict] = {}

    async def setup(self) -> None:
        return None

    async def ensure_github(self, github_id: int, login: str) -> tuple[str, bool]:
        for account in self._accounts.values():
            if account.github_id == github_id:
                self._accounts[account.user_id] = replace(account, github_login=login)
                return account.user_id, False
        user_id = uuid.uuid4().hex
        self._accounts[user_id] = Identity(user_id, github_id, login)
        return user_id, True

    async def identity(self, user_id: str) -> Identity | None:
        return self._accounts.get(user_id)

    async def github_logins(self, user_ids: list[str]) -> dict[str, str]:
        return {u: self._accounts[u].github_login for u in user_ids if u in self._accounts}

    async def add_token(
        self, token: str, user_id: str, kind: str, ttl: int, label: str = ""
    ) -> None:
        self._tokens[token_hash(token)] = {
            "user_id": user_id,
            "kind": kind,
            "label": label,
            "created_at": time.time(),
            "expires_at": time.time() + ttl,
        }

    async def user_for(self, token: str) -> str | None:
        found = await self.lookup(token)
        return found.user_id if found else None

    async def lookup(self, token: str) -> TokenInfo | None:
        row = self._tokens.get(token_hash(token))
        if row is None or row["expires_at"] < time.time():
            return None
        return TokenInfo(row["user_id"], row["kind"], row["label"])

    async def revoke(self, token: str) -> None:
        self._tokens.pop(token_hash(token), None)

    async def tokens(self, user_id: str) -> list[dict]:
        return [
            {k: v for k, v in row.items() if k != "user_id"}
            for row in self._tokens.values()
            if row["user_id"] == user_id and row["expires_at"] >= time.time()
        ]

    async def link_discord(self, user_id: str, discord_id: str) -> None:
        others = (a for a in self._accounts.values() if a.user_id != user_id)
        if any(a.discord_id == discord_id for a in others):
            raise DiscordTaken(discord_id)
        account = self._accounts[user_id]
        self._accounts[user_id] = replace(account, discord_id=discord_id, discord_error="")

    async def unlink_discord(self, user_id: str) -> None:
        account = self._accounts[user_id]
        self._accounts[user_id] = replace(account, discord_id=None, digest=False, discord_error="")

    async def set_digest(self, user_id: str, on: bool) -> None:
        self._accounts[user_id] = replace(self._accounts[user_id], digest=on)

    async def set_discord_error(self, user_id: str, error: str) -> None:
        self._accounts[user_id] = replace(self._accounts[user_id], discord_error=error)

    async def digest_subscribers(self) -> list[Subscriber]:
        return [
            Subscriber(a.user_id, a.discord_id)
            for a in self._accounts.values()
            if a.digest and a.discord_id
        ]

    async def forget(self, user_id: str) -> None:
        self._accounts.pop(user_id, None)
        for h in [h for h, row in self._tokens.items() if row["user_id"] == user_id]:
            del self._tokens[h]

    async def close(self) -> None:
        return None


class PostgresCredentialStore:
    """The `credentials` and `tokens` tables in `db.SCHEMA`."""

    def __init__(self, url: str) -> None:
        from norboten_api.db import Postgres

        self.db = Postgres(url)

    async def setup(self) -> None:
        await self.db.setup()

    async def ensure_github(self, github_id: int, login: str) -> tuple[str, bool]:
        """The account for this GitHub user, created at its first sign-in, with the login brought
        up to date. Two sign-ins at once must still make one account, so the insert decides."""
        row = await self.db.returning(
            "INSERT INTO credentials (user_id, github_id, github_login) VALUES (:u, :g, :l) "
            "ON CONFLICT (github_id) DO NOTHING RETURNING user_id",
            u=uuid.uuid4().hex,
            g=github_id,
            l=login,
        )
        if row is not None:
            return row["user_id"], True
        found = await self.db.returning(
            "UPDATE credentials SET github_login = :l WHERE github_id = :g RETURNING user_id",
            g=github_id,
            l=login,
        )
        assert found is not None  # the conflict says the row is there
        return found["user_id"], False

    async def identity(self, user_id: str) -> Identity | None:
        row = await self.db.fetch_one(
            "SELECT user_id, github_id, github_login, discord_id, digest, discord_error "
            "FROM credentials WHERE user_id = :u",
            u=user_id,
        )
        if row is None:
            return None
        return Identity(
            row["user_id"],
            int(row["github_id"]),
            row["github_login"],
            row["discord_id"],
            bool(row["digest"]),
            row["discord_error"] or "",
        )

    async def github_logins(self, user_ids: list[str]) -> dict[str, str]:
        if not user_ids:
            return {}
        rows = await self.db.fetch(
            "SELECT user_id, github_login FROM credentials WHERE user_id = ANY(:ids)",
            ids=list(user_ids),
        )
        return {r["user_id"]: r["github_login"] for r in rows}

    async def add_token(
        self, token: str, user_id: str, kind: str, ttl: int, label: str = ""
    ) -> None:
        await self.db.execute(
            "INSERT INTO tokens (token_hash, user_id, kind, label, expires_at) "
            "VALUES (:t, :u, :k, :l, now() + make_interval(secs => :ttl))",
            t=token_hash(token),
            u=user_id,
            k=kind,
            l=label[:120],
            ttl=ttl,
        )

    async def user_for(self, token: str) -> str | None:
        found = await self.lookup(token)
        return found.user_id if found else None

    async def lookup(self, token: str) -> TokenInfo | None:
        row = await self.db.returning(
            "UPDATE tokens SET last_used_at = now() WHERE token_hash = :t AND expires_at > now() "
            "RETURNING user_id, kind, label",
            t=token_hash(token),
        )
        return TokenInfo(row["user_id"], row["kind"], row["label"] or "") if row else None

    async def revoke(self, token: str) -> None:
        await self.db.execute("DELETE FROM tokens WHERE token_hash = :t", t=token_hash(token))

    async def tokens(self, user_id: str) -> list[dict]:
        rows = await self.db.fetch(
            "SELECT kind, label, extract(epoch from created_at) AS created_at, "
            "extract(epoch from expires_at) AS expires_at FROM tokens "
            "WHERE user_id = :u AND expires_at > now() ORDER BY created_at DESC",
            u=user_id,
        )
        return [dict(r) | {k: float(r[k]) for k in ("created_at", "expires_at")} for r in rows]

    async def link_discord(self, user_id: str, discord_id: str) -> None:
        from sqlalchemy.exc import IntegrityError

        try:
            await self.db.execute(
                "UPDATE credentials SET discord_id = :d, discord_error = '' WHERE user_id = :u",
                u=user_id,
                d=discord_id,
            )
        except IntegrityError as e:
            raise DiscordTaken(discord_id) from e

    async def unlink_discord(self, user_id: str) -> None:
        await self.db.execute(
            "UPDATE credentials SET discord_id = NULL, digest = false, discord_error = '' "
            "WHERE user_id = :u",
            u=user_id,
        )

    async def set_digest(self, user_id: str, on: bool) -> None:
        await self.db.execute(
            "UPDATE credentials SET digest = :d WHERE user_id = :u", u=user_id, d=on
        )

    async def set_discord_error(self, user_id: str, error: str) -> None:
        await self.db.execute(
            "UPDATE credentials SET discord_error = :e WHERE user_id = :u", u=user_id, e=error
        )

    async def digest_subscribers(self) -> list[Subscriber]:
        rows = await self.db.fetch(
            "SELECT user_id, discord_id FROM credentials "
            "WHERE digest AND discord_id IS NOT NULL ORDER BY created_at"
        )
        return [Subscriber(r["user_id"], r["discord_id"]) for r in rows]

    async def forget(self, user_id: str) -> None:
        """The row and every token on it: `tokens.user_id` cascades from `credentials`."""
        await self.db.execute("DELETE FROM credentials WHERE user_id = :u", u=user_id)

    async def close(self) -> None:
        await self.db.close()


def build(url: str) -> CredentialStore:
    from norboten_api.db import is_postgres

    return PostgresCredentialStore(url) if is_postgres(url) else MemoryCredentialStore()
