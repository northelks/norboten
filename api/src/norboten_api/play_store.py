"""Where live sessions and their recordings live.

A play session is a short-lived, append-only thing: a header, then batches of frames arriving every
couple of seconds until it ends. In PostgreSQL (`db.SCHEMA`):

    play_sessions   pk session_id; expires_at a week after it started
    play_batches    pk (session_id, seq); frames, commands and diffs, deleted with the session

A terminal recording is interesting for a week and a liability for ever, so everything expires:
`purge()` deletes what is past `expires_at`, and the API runs it on start and every hour. What
viewers of a live session receive does not come from here at all — frames are published on Redis
as they arrive (`live.py`); this is the recording, for replays and late joiners.
"""

from __future__ import annotations

import json
import time
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

#: A session with no frames for this long is not live any more. The recorder flushes every ~2s.
LIVE_AFTER_SECONDS = 25.0

#: How long a recording is kept.
RETENTION_SECONDS = 7 * 24 * 3600


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlaySession(_Model):
    session_id: str = Field(min_length=8, max_length=64)
    user_id: str
    nick: str
    country: str = ""
    lab_id: str
    lab_title: str = ""
    width: int = Field(ge=20, le=400)
    height: int = Field(ge=5, le=200)
    started_at: float = Field(default_factory=time.time)
    last_frame_at: float = Field(default_factory=time.time)
    ended_at: float | None = None
    frames: int = 0
    commands: int = 0
    passed: bool | None = None
    seed: bool = False  # a canned recording shipped with the site

    @property
    def live(self) -> bool:
        return self.ended_at is None and time.time() - self.last_frame_at < LIVE_AFTER_SECONDS

    @property
    def duration(self) -> float:
        return (self.ended_at or self.last_frame_at) - self.started_at

    def header(self) -> dict:
        """The asciicast v2 header for this recording."""
        return {
            "version": 2,
            "width": self.width,
            "height": self.height,
            "timestamp": int(self.started_at),
            "title": f"{self.nick} · {self.lab_title or self.lab_id}",
        }


class FrameBatch(_Model):
    """One flush from the recorder: what crossed the terminal, plus what it changed."""

    seq: int = Field(ge=0)
    at: float  # seconds into the recording, for the first event in this batch
    events: list[list] = Field(default_factory=list)  # [time, "o"|"i", data]
    commands: list[dict] = Field(default_factory=list)  # {"at": float, "text": str}
    changes: list[dict] = Field(default_factory=list)  # {"path", "diff", "truncated", "command"}


class PlayStore(Protocol):
    async def setup(self) -> None: ...
    async def start(self, session: PlaySession) -> None: ...
    async def session(self, session_id: str) -> PlaySession | None: ...
    async def append(self, session_id: str, batch: FrameBatch) -> PlaySession | None: ...
    async def end(self, session_id: str, passed: bool | None = None) -> None: ...
    async def batches(self, session_id: str, after: int = -1) -> list[FrameBatch]: ...
    async def live(self, limit: int = 20) -> list[PlaySession]: ...
    async def recent(self, limit: int = 20) -> list[PlaySession]: ...
    async def purge(self) -> int: ...
    async def forget(self, user_id: str) -> None: ...
    async def close(self) -> None: ...


class MemoryPlayStore:
    def __init__(self) -> None:
        self._sessions: dict[str, PlaySession] = {}
        self._batches: dict[str, list[FrameBatch]] = {}

    async def setup(self) -> None:
        return None

    async def start(self, session: PlaySession) -> None:
        self._sessions[session.session_id] = session
        self._batches.setdefault(session.session_id, [])

    async def session(self, session_id: str) -> PlaySession | None:
        return self._sessions.get(session_id)

    async def append(self, session_id: str, batch: FrameBatch) -> PlaySession | None:
        session = self._sessions.get(session_id)
        if session is None or session.ended_at is not None:
            return None
        self._batches.setdefault(session_id, []).append(batch)
        updated = session.model_copy(
            update={
                "last_frame_at": time.time(),
                "frames": session.frames + len(batch.events),
                "commands": session.commands + len(batch.commands),
            }
        )
        self._sessions[session_id] = updated
        return updated

    async def end(self, session_id: str, passed: bool | None = None) -> None:
        session = self._sessions.get(session_id)
        if session is not None:
            self._sessions[session_id] = session.model_copy(
                update={"ended_at": time.time(), "passed": passed}
            )

    async def batches(self, session_id: str, after: int = -1) -> list[FrameBatch]:
        return [b for b in self._batches.get(session_id, []) if b.seq > after]

    async def live(self, limit: int = 20) -> list[PlaySession]:
        out = [s for s in self._sessions.values() if s.live]
        out.sort(key=lambda s: s.started_at, reverse=True)
        return out[:limit]

    async def recent(self, limit: int = 20) -> list[PlaySession]:
        out = [s for s in self._sessions.values() if not s.live]
        out.sort(key=lambda s: s.ended_at or s.last_frame_at, reverse=True)
        return out[:limit]

    async def purge(self) -> int:
        cutoff = time.time() - RETENTION_SECONDS
        old = [sid for sid, s in self._sessions.items() if s.started_at < cutoff]
        for sid in old:
            self._sessions.pop(sid, None)
            self._batches.pop(sid, None)
        return len(old)

    async def forget(self, user_id: str) -> None:
        for sid in [sid for sid, s in self._sessions.items() if s.user_id == user_id]:
            self._sessions.pop(sid, None)
            self._batches.pop(sid, None)

    async def close(self) -> None:
        return None


_SESSION_COLUMNS = (
    "session_id, user_id, nick, country, lab_id, lab_title, width, height, "
    "extract(epoch from started_at) AS started_at, "
    "extract(epoch from last_frame_at) AS last_frame_at, "
    "extract(epoch from ended_at) AS ended_at, frames, commands, passed, seed"
)


class PostgresPlayStore:
    """PostgreSQL-backed store."""

    def __init__(self, url: str) -> None:
        from norboten_api.db import Postgres

        self.db = Postgres(url)

    async def setup(self) -> None:
        await self.db.setup()
        await self.purge()

    @staticmethod
    def _session(row) -> PlaySession:
        data = dict(row)
        for key in ("started_at", "last_frame_at", "ended_at"):
            if data[key] is not None:
                data[key] = float(data[key])
        return PlaySession.model_validate(data)

    async def start(self, session: PlaySession) -> None:
        await self.db.execute(
            "INSERT INTO play_sessions (session_id, user_id, nick, country, lab_id, lab_title, "
            "width, height, started_at, last_frame_at, frames, commands, seed, expires_at) "
            "VALUES (:session_id, :user_id, :nick, :country, :lab_id, :lab_title, :width, "
            ":height, to_timestamp(:started_at), to_timestamp(:last_frame_at), :frames, "
            ":commands, :seed, to_timestamp(:started_at + :keep))",
            **session.model_dump(exclude={"ended_at", "passed"}),
            keep=RETENTION_SECONDS,
        )

    async def session(self, session_id: str) -> PlaySession | None:
        row = await self.db.fetch_one(
            f"SELECT {_SESSION_COLUMNS} FROM play_sessions WHERE session_id = :s", s=session_id
        )
        return self._session(row) if row else None

    async def append(self, session_id: str, batch: FrameBatch) -> PlaySession | None:
        from sqlalchemy import text

        async with self.db.engine.begin() as conn:
            updated = (
                (
                    await conn.execute(
                        text(
                            "UPDATE play_sessions SET last_frame_at = now(), "
                            "frames = frames + :f, commands = commands + :c "
                            "WHERE session_id = :s AND ended_at IS NULL "
                            f"RETURNING {_SESSION_COLUMNS}"
                        ),
                        {"s": session_id, "f": len(batch.events), "c": len(batch.commands)},
                    )
                )
                .mappings()
                .first()
            )
            if updated is None:
                return None
            await conn.execute(
                text(
                    "INSERT INTO play_batches (session_id, seq, at, events, commands, changes) "
                    "VALUES (:s, :seq, :at, CAST(:events AS JSONB), CAST(:commands AS JSONB), "
                    "CAST(:changes AS JSONB)) ON CONFLICT (session_id, seq) DO NOTHING"
                ),
                {
                    "s": session_id,
                    "seq": batch.seq,
                    "at": batch.at,
                    "events": json.dumps(batch.events),
                    "commands": json.dumps(batch.commands),
                    "changes": json.dumps(batch.changes),
                },
            )
        return self._session(updated)

    async def end(self, session_id: str, passed: bool | None = None) -> None:
        await self.db.execute(
            "UPDATE play_sessions SET ended_at = now(), passed = :p "
            "WHERE session_id = :s AND ended_at IS NULL",
            s=session_id,
            p=passed,
        )

    async def batches(self, session_id: str, after: int = -1) -> list[FrameBatch]:
        rows = await self.db.fetch(
            "SELECT seq, at, events, commands, changes FROM play_batches "
            "WHERE session_id = :s AND seq > :after ORDER BY seq",
            s=session_id,
            after=after,
        )
        return [FrameBatch.model_validate(dict(row)) for row in rows]

    async def live(self, limit: int = 20) -> list[PlaySession]:
        rows = await self.db.fetch(
            f"SELECT {_SESSION_COLUMNS} FROM play_sessions WHERE ended_at IS NULL "
            "AND last_frame_at > now() - make_interval(secs => :live) "
            "ORDER BY started_at DESC LIMIT :limit",
            live=LIVE_AFTER_SECONDS,
            limit=limit,
        )
        return [self._session(row) for row in rows]

    async def recent(self, limit: int = 20) -> list[PlaySession]:
        rows = await self.db.fetch(
            f"SELECT {_SESSION_COLUMNS} FROM play_sessions WHERE ended_at IS NOT NULL "
            "OR last_frame_at <= now() - make_interval(secs => :live) "
            "ORDER BY coalesce(ended_at, last_frame_at) DESC LIMIT :limit",
            live=LIVE_AFTER_SECONDS,
            limit=limit,
        )
        return [self._session(row) for row in rows]

    async def purge(self) -> int:
        return await self.db.execute("DELETE FROM play_sessions WHERE expires_at < now()")

    async def forget(self, user_id: str) -> None:
        """Recordings and their frames: `play_batches.session_id` cascades."""
        await self.db.execute("DELETE FROM play_sessions WHERE user_id = :u", u=user_id)

    async def close(self) -> None:
        await self.db.close()


def build(url: str) -> PlayStore:
    """The server's database URL, or `memory://`."""
    from norboten_api.db import is_postgres

    return PostgresPlayStore(url) if is_postgres(url) else MemoryPlayStore()
