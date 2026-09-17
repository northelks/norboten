"""A sign-in or a link that has started and not finished: the only state the OAuth flows keep.

One row per flow, in PostgreSQL rather than Redis for the reason the six-digit codes were there
before them: a person who is approving on GitHub while the API restarts must still land signed in.
Every row expires (fifteen minutes; a one-time code a minute) and is used once — `take` deletes it
as it reads it, so a replayed callback or a second exchange of the same code finds nothing.

Kinds:

* `device` — a terminal's device flow: GitHub's `device_code` (never sent to the terminal), its
  polling interval, the terminal's label;
* `web` — the site's flow: its own `state` (checked in the browser), `remember`, where to return;
* `once` — the one-time code the callback hands the site in a URL fragment, for a token;
* `discord-link` — linking Discord to a signed-in account: the account and whether to join.
"""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass
from typing import Protocol

#: A flow that is not finished in this long is abandoned.
FLOW_SECONDS = 15 * 60
#: The one-time code between the callback and the page that exchanges it.
ONCE_SECONDS = 60


@dataclass(frozen=True)
class Pending:
    id: str
    kind: str
    data: dict
    expires_at: float


def new_id() -> str:
    return secrets.token_urlsafe(24)


class PendingStore(Protocol):
    async def setup(self) -> None: ...
    async def create(self, kind: str, data: dict, ttl: int = FLOW_SECONDS) -> str: ...
    async def get(self, pending_id: str, kind: str) -> Pending | None: ...
    async def update(self, pending_id: str, data: dict) -> None: ...
    async def take(self, pending_id: str, kind: str) -> Pending | None: ...
    async def close(self) -> None: ...


class MemoryPendingStore:
    def __init__(self) -> None:
        self._rows: dict[str, Pending] = {}

    async def setup(self) -> None:
        return None

    async def create(self, kind: str, data: dict, ttl: int = FLOW_SECONDS) -> str:
        pending_id = new_id()
        self._rows[pending_id] = Pending(pending_id, kind, dict(data), time.time() + ttl)
        return pending_id

    async def get(self, pending_id: str, kind: str) -> Pending | None:
        row = self._rows.get(pending_id)
        if row is None or row.kind != kind:
            return None
        if row.expires_at <= time.time():
            self._rows.pop(pending_id, None)
            return None
        return row

    async def update(self, pending_id: str, data: dict) -> None:
        row = self._rows.get(pending_id)
        if row is not None:
            self._rows[pending_id] = Pending(row.id, row.kind, dict(data), row.expires_at)

    async def take(self, pending_id: str, kind: str) -> Pending | None:
        row = await self.get(pending_id, kind)
        if row is not None:
            self._rows.pop(pending_id, None)
        return row

    async def close(self) -> None:
        return None


class PostgresPendingStore:
    """The `pending_sign_ins` table in `db.SCHEMA`."""

    def __init__(self, url: str) -> None:
        from norboten_api.db import Postgres

        self.db = Postgres(url)

    async def setup(self) -> None:
        await self.db.setup()

    async def create(self, kind: str, data: dict, ttl: int = FLOW_SECONDS) -> str:
        pending_id = new_id()
        await self.db.execute(
            "INSERT INTO pending_sign_ins (id, kind, data, expires_at) "
            "VALUES (:i, :k, CAST(:d AS jsonb), now() + make_interval(secs => :ttl))",
            i=pending_id,
            k=kind,
            d=json.dumps(data),
            ttl=ttl,
        )
        return pending_id

    @staticmethod
    def _row(row) -> Pending:
        data = row["data"]
        return Pending(
            row["id"],
            row["kind"],
            data if isinstance(data, dict) else json.loads(data),
            float(row["expires_at"]),
        )

    async def get(self, pending_id: str, kind: str) -> Pending | None:
        row = await self.db.fetch_one(
            "SELECT id, kind, data, extract(epoch from expires_at) AS expires_at "
            "FROM pending_sign_ins WHERE id = :i AND kind = :k AND expires_at > now()",
            i=pending_id,
            k=kind,
        )
        return self._row(row) if row else None

    async def update(self, pending_id: str, data: dict) -> None:
        await self.db.execute(
            "UPDATE pending_sign_ins SET data = CAST(:d AS jsonb) WHERE id = :i",
            i=pending_id,
            d=json.dumps(data),
        )

    async def take(self, pending_id: str, kind: str) -> Pending | None:
        # expired rows go on the way, so the table never keeps an abandoned flow for long
        await self.db.execute("DELETE FROM pending_sign_ins WHERE expires_at <= now()")
        row = await self.db.returning(
            "DELETE FROM pending_sign_ins WHERE id = :i AND kind = :k "
            "RETURNING id, kind, data, extract(epoch from expires_at) AS expires_at",
            i=pending_id,
            k=kind,
        )
        return self._row(row) if row else None

    async def close(self) -> None:
        await self.db.close()


def build(url: str) -> PendingStore:
    from norboten_api.db import is_postgres

    return PostgresPendingStore(url) if is_postgres(url) else MemoryPendingStore()
