"""Loading: the same two frames from the sample population or from PostgreSQL."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class Frames:
    users: pd.DataFrame  # user_id, nick, country, created_at (datetime), seed
    attempts: pd.DataFrame  # one row per attempt; started_at as datetime, topics as a list
    source: str  # "sample" or "production"

    @property
    def labs(self) -> pd.DataFrame:
        return self.attempts[self.attempts.kind == "lab"]

    @property
    def quizzes(self) -> pd.DataFrame:
        return self.attempts[self.attempts.kind == "quiz"]


def _frames(users: list[dict], attempts: list[dict], source: str) -> Frames:
    u = pd.DataFrame(users)
    a = pd.DataFrame(attempts)
    if not u.empty:
        u["created_at"] = pd.to_datetime(u["created_at"], unit="s", utc=True)
    if not a.empty:
        a["started_at"] = pd.to_datetime(a["started_at"], unit="s", utc=True)
        a["minutes"] = a["duration_seconds"] / 60
        a = a.sort_values("started_at").reset_index(drop=True)
    return Frames(u, a, source)


def from_seed(path: Path) -> Frames:
    payload = json.loads(path.read_text())
    return _frames(payload["users"], payload["attempts"], "sample")


async def _read_postgres(url: str) -> tuple[list[dict], list[dict]]:
    from norboten_api.db import Postgres

    db = Postgres(url)
    try:
        users = await db.fetch(
            "SELECT user_id, nick, country, extract(epoch from created_at) AS created_at, seed "
            "FROM users"
        )
        attempts = await db.fetch(
            "SELECT user_id, kind, lab_id, extract(epoch from started_at) AS started_at, "
            "duration_seconds, score_percent, passed, rated, within_limit, difficulty, topics "
            "FROM attempts"
        )
    finally:
        await db.close()
    return [dict(r) for r in users], [dict(r) for r in attempts]


def from_postgres(url: str) -> Frames:
    import asyncio

    users, attempts = asyncio.run(_read_postgres(url))
    for row in users:
        row["created_at"] = float(row["created_at"])
    for row in attempts:
        row["started_at"] = float(row["started_at"])
    return _frames(users, attempts, "production")
