"""Where rated attempts live between being issued and being judged (docs/lab-spec.md §13), and
rated theory runs between the first question and the last (docs/quiz-spec.md §6).

One row per attempt or run. What the server queries on — the attempt, its owner, whether it is
open and when it expires — are columns; everything else, the key and the records included, is one
JSON document, because it is only ever read whole. Two implementations behind one protocol, as with
every other store: memory for tests and a laptop, PostgreSQL for the server (`db.SCHEMA`).
"""

from __future__ import annotations

import json
import time
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

Outcome = Literal["", "passed", "failed", "abandoned", "expired"]


class CheckVerdict(BaseModel):
    """What a learner is told about one check: no message, no evidence, no criterion."""

    id: str
    objective: int
    passed: bool


class Received(BaseModel):
    record: dict
    received_at: float


class RatedAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str
    user_id: str
    lab_id: str
    lab_version: str
    image: str
    nonce: str
    key: str  # hex; it signs the guest's records and is useless for anything else
    issued_at: float = Field(default_factory=time.time)
    expires_at: float
    records: dict[str, Received] = Field(default_factory=dict)
    outcome: Outcome = ""
    closed_at: float | None = None
    score_percent: int = 0
    within_limit: bool = False
    duration_seconds: int = 0
    checks: list[CheckVerdict] = Field(default_factory=list)
    rating_delta: dict[str, float] = Field(default_factory=dict)

    @property
    def open(self) -> bool:
        return not self.outcome


class ServedQuestion(BaseModel):
    """A rated question as it was served: when, and what came back."""

    id: str
    asked_at: float
    selected: list[str] | None = None
    correct: bool = False
    expired: bool = False


class RatedQuizSession(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attempt_id: str
    user_id: str
    topic: str
    issued_at: float = Field(default_factory=time.time)
    expires_at: float
    order: list[str]  # the questions this run will ask, in order
    served: list[ServedQuestion] = Field(default_factory=list)
    outcome: Outcome = ""
    closed_at: float | None = None
    score_percent: int = 0
    difficulty: int = 1
    rating_delta: dict[str, float] = Field(default_factory=dict)

    @property
    def open(self) -> bool:
        return not self.outcome


class RatedStore[Row: (RatedAttempt, RatedQuizSession)](Protocol):
    async def setup(self) -> None: ...
    async def put(self, row: Row) -> None: ...
    async def get(self, attempt_id: str) -> Row | None: ...
    async def open_for(self, user_id: str) -> list[Row]: ...
    async def expired(self, now: float) -> list[Row]: ...
    async def forget(self, user_id: str) -> None: ...
    async def close(self) -> None: ...


class MemoryRatedStore[Row: (RatedAttempt, RatedQuizSession)]:
    def __init__(self, model: type[Row]) -> None:
        self.model = model
        self._rows: dict[str, Row] = {}

    async def setup(self) -> None:
        return None

    async def put(self, row: Row) -> None:
        self._rows[row.attempt_id] = row.model_copy(deep=True)

    async def get(self, attempt_id: str) -> Row | None:
        row = self._rows.get(attempt_id)
        return row.model_copy(deep=True) if row else None

    async def open_for(self, user_id: str) -> list[Row]:
        return [
            a.model_copy(deep=True) for a in self._rows.values() if a.user_id == user_id and a.open
        ]

    async def expired(self, now: float) -> list[Row]:
        return [
            a.model_copy(deep=True) for a in self._rows.values() if a.open and a.expires_at < now
        ]

    async def forget(self, user_id: str) -> None:
        for attempt_id in [k for k, a in self._rows.items() if a.user_id == user_id]:
            del self._rows[attempt_id]

    async def close(self) -> None:
        return None


class PostgresRatedStore[Row: (RatedAttempt, RatedQuizSession)]:
    """One table per kind, the same five columns in each (`db.SCHEMA`)."""

    def __init__(self, url: str, model: type[Row], table: str) -> None:
        from norboten_api.db import Postgres

        self.db = Postgres(url)
        self.model = model
        self.table = table

    async def setup(self) -> None:
        await self.db.setup()

    async def put(self, row: Row) -> None:
        await self.db.execute(
            f"INSERT INTO {self.table} (attempt_id, user_id, open, expires_at, data) "
            "VALUES (:attempt_id, :user_id, :open, to_timestamp(:expires_at), "
            "CAST(:data AS JSONB)) "
            "ON CONFLICT (attempt_id) DO UPDATE SET open = EXCLUDED.open, data = EXCLUDED.data",
            attempt_id=row.attempt_id,
            user_id=row.user_id,
            open=row.open,
            expires_at=row.expires_at,
            data=row.model_dump_json(),
        )

    def _load(self, row) -> Row:
        data = row["data"]
        return self.model.model_validate(json.loads(data) if isinstance(data, str) else data)

    async def get(self, attempt_id: str) -> Row | None:
        row = await self.db.fetch_one(
            f"SELECT data FROM {self.table} WHERE attempt_id = :a", a=attempt_id
        )
        return self._load(row) if row else None

    async def open_for(self, user_id: str) -> list[Row]:
        rows = await self.db.fetch(
            f"SELECT data FROM {self.table} WHERE user_id = :u AND open", u=user_id
        )
        return [self._load(r) for r in rows]

    async def expired(self, now: float) -> list[Row]:
        rows = await self.db.fetch(
            f"SELECT data FROM {self.table} WHERE open AND expires_at < to_timestamp(:now)",
            now=now,
        )
        return [self._load(r) for r in rows]

    async def forget(self, user_id: str) -> None:
        await self.db.execute(f"DELETE FROM {self.table} WHERE user_id = :u", u=user_id)

    async def close(self) -> None:
        await self.db.close()


def build(url: str) -> RatedStore[RatedAttempt]:
    from norboten_api.db import is_postgres

    if is_postgres(url):
        return PostgresRatedStore(url, RatedAttempt, "rated_attempts")
    return MemoryRatedStore(RatedAttempt)


def build_quiz(url: str) -> RatedStore[RatedQuizSession]:
    from norboten_api.db import is_postgres

    if is_postgres(url):
        return PostgresRatedStore(url, RatedQuizSession, "rated_quiz_sessions")
    return MemoryRatedStore(RatedQuizSession)
