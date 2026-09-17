"""The one PostgreSQL database behind every store, and the schema it holds.

Everything the server keeps lives here: events, accounts and credentials, attempts
and ratings, play sessions and their frames. One database, one connection pool shared by the
stores, and one schema applied on start — there are few enough tables that a migration tool would
be more machinery than the schema itself. Every statement is idempotent, so applying it to a
database that already has the tables changes nothing; a column added later is an `ALTER … ADD
COLUMN IF NOT EXISTS` appended here.

Timestamps are `timestamptz` in the database and Unix seconds in Python; the conversion happens at
the edge of each query (`to_timestamp` in, `extract(epoch …)` out).
"""

from __future__ import annotations

from functools import lru_cache

SCHEMA: tuple[str, ...] = (
    # -- events ----------------------------------------------------------------------------
    # generated questions were served from here until 2026-09-15; they live in the repository now
    "DROP TABLE IF EXISTS questions",
    """
    CREATE TABLE IF NOT EXISTS events (
        id         BIGSERIAL PRIMARY KEY,
        kind       TEXT NOT NULL,
        payload    JSONB NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS events_kind_idx ON events (kind, created_at DESC)",
    # -- accounts --------------------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id     TEXT PRIMARY KEY,
        nick        TEXT NOT NULL UNIQUE,
        country     CHAR(2) NOT NULL,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        seed        BOOLEAN NOT NULL DEFAULT false
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS credentials (
        user_id        TEXT PRIMARY KEY,
        github_id      BIGINT,
        github_login   TEXT NOT NULL DEFAULT '',
        created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    # passwords went away on 2026-09-16, and email the same day: an account is a GitHub account.
    # No real account existed, so nothing is migrated — the old columns simply go.
    "ALTER TABLE credentials DROP COLUMN IF EXISTS password_hash",
    "ALTER TABLE credentials DROP COLUMN IF EXISTS email",
    "ALTER TABLE credentials ADD COLUMN IF NOT EXISTS github_id BIGINT",
    "ALTER TABLE credentials ADD COLUMN IF NOT EXISTS github_login TEXT NOT NULL DEFAULT ''",
    "CREATE UNIQUE INDEX IF NOT EXISTS credentials_github_idx ON credentials (github_id)",
    """
    CREATE TABLE IF NOT EXISTS tokens (
        token_hash   TEXT PRIMARY KEY,
        user_id      TEXT NOT NULL REFERENCES credentials (user_id) ON DELETE CASCADE,
        kind         TEXT NOT NULL,
        label        TEXT NOT NULL DEFAULT '',
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        expires_at   TIMESTAMPTZ NOT NULL,
        last_used_at TIMESTAMPTZ
    )
    """,
    "CREATE INDEX IF NOT EXISTS tokens_user_idx ON tokens (user_id)",
    # the weekly learner digest (norboten_api/digest.py): opt-in, off by default, and a Discord
    # direct message, so it needs a linked Discord user
    "ALTER TABLE credentials ADD COLUMN IF NOT EXISTS digest BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE credentials ADD COLUMN IF NOT EXISTS discord_id TEXT",
    "ALTER TABLE credentials ADD COLUMN IF NOT EXISTS discord_error TEXT NOT NULL DEFAULT ''",
    "CREATE UNIQUE INDEX IF NOT EXISTS credentials_discord_idx ON credentials (discord_id)",
    # the six-digit codes went with email sign-in
    "DROP TABLE IF EXISTS login_codes",
    # a GitHub sign-in or a Discord link that has started and not finished (pending.py): in the
    # database and not Redis, so a restart mid-sign-in strands nobody
    """
    CREATE TABLE IF NOT EXISTS pending_sign_ins (
        id          TEXT PRIMARY KEY,
        kind        TEXT NOT NULL,
        data        JSONB NOT NULL,
        expires_at  TIMESTAMPTZ NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS pending_sign_ins_expiry_idx ON pending_sign_ins (expires_at)",
    """
    CREATE TABLE IF NOT EXISTS attempts (
        id                BIGSERIAL PRIMARY KEY,
        user_id           TEXT NOT NULL,
        kind              TEXT NOT NULL,
        lab_id            TEXT NOT NULL,
        started_at        TIMESTAMPTZ NOT NULL,
        duration_seconds  INTEGER NOT NULL,
        score_percent     SMALLINT NOT NULL,
        passed            BOOLEAN NOT NULL,
        rated             BOOLEAN NOT NULL,
        within_limit      BOOLEAN NOT NULL DEFAULT true,
        difficulty        SMALLINT NOT NULL,
        topics            TEXT[] NOT NULL,
        rating_delta      JSONB NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    "CREATE INDEX IF NOT EXISTS attempts_user_idx ON attempts (user_id, started_at DESC)",
    "CREATE INDEX IF NOT EXISTS attempts_lab_idx ON attempts (lab_id, started_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS ratings (
        user_id     TEXT NOT NULL,
        topic       TEXT NOT NULL,
        r           DOUBLE PRECISION NOT NULL,
        rd          DOUBLE PRECISION NOT NULL,
        sigma       DOUBLE PRECISION NOT NULL,
        games       INTEGER NOT NULL,
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (user_id, topic)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ratings_topic_idx ON ratings (topic)",
    # -- rated attempts (docs/lab-spec.md §13) ---------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS rated_attempts (
        attempt_id  TEXT PRIMARY KEY,
        user_id     TEXT NOT NULL,
        open        BOOLEAN NOT NULL,
        expires_at  TIMESTAMPTZ NOT NULL,
        data        JSONB NOT NULL,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS rated_attempts_user_idx ON rated_attempts (user_id) WHERE open",
    "CREATE INDEX IF NOT EXISTS rated_attempts_expiry_idx ON rated_attempts (expires_at) "
    "WHERE open",
    # -- rated theory runs (docs/quiz-spec.md §6): the same shape, one row per run ------------
    """
    CREATE TABLE IF NOT EXISTS rated_quiz_sessions (
        attempt_id  TEXT PRIMARY KEY,
        user_id     TEXT NOT NULL,
        open        BOOLEAN NOT NULL,
        expires_at  TIMESTAMPTZ NOT NULL,
        data        JSONB NOT NULL,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX IF NOT EXISTS rated_quiz_user_idx ON rated_quiz_sessions (user_id) WHERE open",
    "CREATE INDEX IF NOT EXISTS rated_quiz_expiry_idx ON rated_quiz_sessions (expires_at) "
    "WHERE open",
    # -- play ------------------------------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS play_sessions (
        session_id     TEXT PRIMARY KEY,
        user_id        TEXT NOT NULL,
        nick           TEXT NOT NULL,
        country        TEXT NOT NULL DEFAULT '',
        lab_id         TEXT NOT NULL,
        lab_title      TEXT NOT NULL DEFAULT '',
        width          SMALLINT NOT NULL,
        height         SMALLINT NOT NULL,
        started_at     TIMESTAMPTZ NOT NULL,
        last_frame_at  TIMESTAMPTZ NOT NULL,
        ended_at       TIMESTAMPTZ,
        frames         INTEGER NOT NULL DEFAULT 0,
        commands       INTEGER NOT NULL DEFAULT 0,
        passed         BOOLEAN,
        seed           BOOLEAN NOT NULL DEFAULT false,
        expires_at     TIMESTAMPTZ NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS play_sessions_recent_idx ON play_sessions (last_frame_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS play_batches (
        session_id  TEXT NOT NULL REFERENCES play_sessions (session_id) ON DELETE CASCADE,
        seq         INTEGER NOT NULL,
        at          DOUBLE PRECISION NOT NULL,
        events      JSONB NOT NULL,
        commands    JSONB NOT NULL,
        changes     JSONB NOT NULL,
        PRIMARY KEY (session_id, seq)
    )
    """,
)


def is_postgres(url: str) -> bool:
    return url.startswith(("postgresql", "postgres://"))


def async_url(url: str) -> str:
    """`postgres://…` as compose files write it, as the driver SQLAlchemy needs."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


@lru_cache(maxsize=4)
def engine(url: str):
    """One pool per database URL, shared by every store that uses it."""
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(async_url(url), pool_pre_ping=True, pool_size=10, max_overflow=5)


async def apply_schema(url: str) -> None:
    from sqlalchemy import text

    async with engine(url).begin() as conn:
        # two API processes starting together must not race on CREATE TABLE
        await conn.execute(text("SELECT pg_advisory_xact_lock(4242)"))
        for statement in SCHEMA:
            await conn.execute(text(statement))


class Postgres:
    """The query helpers every Postgres store shares."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.engine = engine(url)

    async def setup(self) -> None:
        await apply_schema(self.url)

    async def fetch(self, sql: str, **params) -> list:
        from sqlalchemy import text

        async with self.engine.connect() as conn:
            result = await conn.execute(text(sql), params)
            return list(result.mappings().all())

    async def fetch_one(self, sql: str, **params):
        rows = await self.fetch(sql, **params)
        return rows[0] if rows else None

    async def returning(self, sql: str, **params):
        """A write that returns a row (UPDATE … RETURNING), committed."""
        from sqlalchemy import text

        async with self.engine.begin() as conn:
            result = await conn.execute(text(sql), params)
            return result.mappings().first()

    async def execute(self, sql: str, **params) -> int:
        from sqlalchemy import text

        async with self.engine.begin() as conn:
            result = await conn.execute(text(sql), params)
            return result.rowcount or 0

    async def execute_many(self, sql: str, rows: list[dict]) -> None:
        from sqlalchemy import text

        if not rows:
            return
        async with self.engine.begin() as conn:
            await conn.execute(text(sql), rows)

    async def close(self) -> None:
        await self.engine.dispose()
        engine.cache_clear()
