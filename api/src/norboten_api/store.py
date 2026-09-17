"""Where events — opt-in progress, opt-in telemetry, tutor and consultant use — live.

Two implementations: an in-memory one (development, tests, and a server with no database) and a
PostgreSQL one. Both satisfy the same small protocol, so a route never knows which it has.
"""

from __future__ import annotations

import json
import time
from typing import Protocol


class Store(Protocol):
    async def setup(self) -> None: ...
    async def record_event(self, kind: str, payload: dict) -> None: ...
    async def events(self, kind: str, limit: int = 100) -> list[dict]: ...
    async def close(self) -> None: ...


class MemoryStore:
    def __init__(self) -> None:
        self._events: list[tuple[str, dict, float]] = []

    async def setup(self) -> None:
        return None

    async def record_event(self, kind: str, payload: dict) -> None:
        self._events.append((kind, payload, time.time()))

    async def events(self, kind: str, limit: int = 100) -> list[dict]:
        return [p for k, p, _ in self._events if k == kind][-limit:]

    async def close(self) -> None:
        return None


class PostgresStore:
    """PostgreSQL-backed store; the tables are in `db.SCHEMA`."""

    def __init__(self, url: str) -> None:
        from norboten_api.db import Postgres

        self.db = Postgres(url)

    async def setup(self) -> None:
        await self.db.setup()

    async def record_event(self, kind: str, payload: dict) -> None:
        await self.db.execute(
            "INSERT INTO events (kind, payload) VALUES (:kind, CAST(:payload AS JSONB))",
            kind=kind,
            payload=json.dumps(payload),
        )

    async def events(self, kind: str, limit: int = 100) -> list[dict]:
        rows = await self.db.fetch(
            "SELECT payload FROM events WHERE kind = :kind ORDER BY id DESC LIMIT :limit",
            kind=kind,
            limit=limit,
        )
        return [r["payload"] for r in rows]

    async def close(self) -> None:
        await self.db.close()


def build(url: str) -> Store:
    from norboten_api.db import is_postgres

    return PostgresStore(url) if is_postgres(url) else MemoryStore()
