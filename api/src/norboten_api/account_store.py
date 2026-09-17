"""Where accounts, attempts and ratings live.

Two implementations behind one protocol, as with the question store: an in-memory one for tests
and a laptop, and PostgreSQL for the server (`db.SCHEMA`):

    users      pk user_id, nick unique
    attempts   bigserial, indexed by (user_id, started_at desc) and (lab_id, started_at desc)
    ratings    pk (user_id, topic), indexed by topic

The leaderboard reads `ratings` for everyone and joins `users`. The population is small and the
page is cached in Redis, so a materialised board would cost more than it saves.
"""

from __future__ import annotations

import json
from typing import Protocol

from norboten_api.accounts import Attempt, TopicRating, User


class NickTaken(ValueError):
    pass


class AccountStore(Protocol):
    async def setup(self) -> None: ...
    async def put_user(self, user: User) -> None: ...
    async def user(self, user_id: str) -> User | None: ...
    async def user_by_nick(self, nick: str) -> User | None: ...
    async def add_attempt(self, attempt: Attempt) -> None: ...
    async def attempts(self, user_id: str, limit: int = 200) -> list[Attempt]: ...
    async def ratings(self, user_id: str) -> dict[str, TopicRating]: ...
    async def put_ratings(self, ratings: list[TopicRating]) -> None: ...
    async def all_ratings(self, topic: str | None = None) -> list[TopicRating]: ...
    async def users(self, user_ids: list[str]) -> dict[str, User]: ...
    async def close(self) -> None: ...


class MemoryAccountStore:
    def __init__(self) -> None:
        self._users: dict[str, User] = {}
        self._nicks: dict[str, str] = {}
        self._attempts: dict[str, list[Attempt]] = {}
        self._ratings: dict[tuple[str, str], TopicRating] = {}

    async def setup(self) -> None:
        return None

    async def put_user(self, user: User) -> None:
        owner = self._nicks.get(user.nick)
        if owner is not None and owner != user.user_id:
            raise NickTaken(user.nick)
        previous = self._users.get(user.user_id)
        if previous and previous.nick != user.nick:
            self._nicks.pop(previous.nick, None)
        self._users[user.user_id] = user
        self._nicks[user.nick] = user.user_id

    async def user(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    async def user_by_nick(self, nick: str) -> User | None:
        user_id = self._nicks.get(nick)
        return self._users.get(user_id) if user_id else None

    async def add_attempt(self, attempt: Attempt) -> None:
        self._attempts.setdefault(attempt.user_id, []).append(attempt)

    async def attempts(self, user_id: str, limit: int = 200) -> list[Attempt]:
        out = sorted(self._attempts.get(user_id, []), key=lambda a: a.started_at, reverse=True)
        return out[:limit]

    async def ratings(self, user_id: str) -> dict[str, TopicRating]:
        return {t: r for (u, t), r in self._ratings.items() if u == user_id}

    async def put_ratings(self, ratings: list[TopicRating]) -> None:
        for r in ratings:
            self._ratings[(r.user_id, r.topic)] = r

    async def all_ratings(self, topic: str | None = None) -> list[TopicRating]:
        return [r for r in self._ratings.values() if topic is None or r.topic == topic]

    async def users(self, user_ids: list[str]) -> dict[str, User]:
        return {uid: self._users[uid] for uid in user_ids if uid in self._users}

    async def close(self) -> None:
        return None


class PostgresAccountStore:
    """PostgreSQL-backed store."""

    def __init__(self, url: str) -> None:
        from norboten_api.db import Postgres

        self.db = Postgres(url)

    async def setup(self) -> None:
        await self.db.setup()

    # -- users -----------------------------------------------------------------------------

    _USER = (
        "SELECT user_id, nick, country, extract(epoch from created_at) AS created_at, seed "
        "FROM users"
    )

    @staticmethod
    def _user(row) -> User:
        return User(
            user_id=row["user_id"],
            nick=row["nick"],
            country=row["country"],
            created_at=float(row["created_at"]),
            seed=row["seed"],
        )

    async def put_user(self, user: User) -> None:
        from sqlalchemy.exc import IntegrityError

        try:
            await self.db.execute(
                "INSERT INTO users (user_id, nick, country, created_at, seed) "
                "VALUES (:user_id, :nick, :country, to_timestamp(:created_at), :seed) "
                "ON CONFLICT (user_id) DO UPDATE SET nick = EXCLUDED.nick, "
                "country = EXCLUDED.country, seed = EXCLUDED.seed",
                **user.model_dump(),
            )
        except IntegrityError as e:  # the nick is unique; someone else holds it
            raise NickTaken(user.nick) from e

    async def user(self, user_id: str) -> User | None:
        row = await self.db.fetch_one(f"{self._USER} WHERE user_id = :u", u=user_id)
        return self._user(row) if row else None

    async def user_by_nick(self, nick: str) -> User | None:
        row = await self.db.fetch_one(f"{self._USER} WHERE nick = :n", n=nick)
        return self._user(row) if row else None

    async def users(self, user_ids: list[str]) -> dict[str, User]:
        if not user_ids:
            return {}
        rows = await self.db.fetch(
            f"{self._USER} WHERE user_id = ANY(:ids)", ids=sorted(set(user_ids))
        )
        return {row["user_id"]: self._user(row) for row in rows}

    # -- attempts --------------------------------------------------------------------------

    async def add_attempt(self, attempt: Attempt) -> None:
        data = attempt.model_dump()
        data["rating_delta"] = json.dumps(data["rating_delta"])
        await self.db.execute(
            "INSERT INTO attempts (user_id, kind, lab_id, started_at, duration_seconds, "
            "score_percent, passed, rated, within_limit, difficulty, topics, rating_delta) "
            "VALUES (:user_id, :kind, :lab_id, to_timestamp(:started_at), :duration_seconds, "
            ":score_percent, :passed, :rated, :within_limit, :difficulty, :topics, "
            "CAST(:rating_delta AS JSONB))",
            **data,
        )

    async def attempts(self, user_id: str, limit: int = 200) -> list[Attempt]:
        rows = await self.db.fetch(
            "SELECT user_id, kind, lab_id, extract(epoch from started_at) AS started_at, "
            "duration_seconds, score_percent, passed, rated, within_limit, difficulty, topics, "
            "rating_delta FROM attempts WHERE user_id = :u "
            "ORDER BY started_at DESC LIMIT :limit",
            u=user_id,
            limit=limit,
        )
        return [
            Attempt.model_validate(dict(row) | {"started_at": float(row["started_at"])})
            for row in rows
        ]

    # -- ratings ---------------------------------------------------------------------------

    _RATING = (
        "SELECT user_id, topic, r, rd, sigma, games, extract(epoch from updated_at) AS updated_at "
        "FROM ratings"
    )

    @staticmethod
    def _rating(row) -> TopicRating:
        return TopicRating.model_validate(dict(row) | {"updated_at": float(row["updated_at"])})

    async def ratings(self, user_id: str) -> dict[str, TopicRating]:
        rows = await self.db.fetch(f"{self._RATING} WHERE user_id = :u", u=user_id)
        return {row["topic"]: self._rating(row) for row in rows}

    async def put_ratings(self, ratings: list[TopicRating]) -> None:
        await self.db.execute_many(
            "INSERT INTO ratings (user_id, topic, r, rd, sigma, games, updated_at) "
            "VALUES (:user_id, :topic, :r, :rd, :sigma, :games, to_timestamp(:updated_at)) "
            "ON CONFLICT (user_id, topic) DO UPDATE SET r = EXCLUDED.r, rd = EXCLUDED.rd, "
            "sigma = EXCLUDED.sigma, games = EXCLUDED.games, updated_at = EXCLUDED.updated_at",
            [r.model_dump() for r in ratings],
        )

    async def all_ratings(self, topic: str | None = None) -> list[TopicRating]:
        if topic:
            rows = await self.db.fetch(f"{self._RATING} WHERE topic = :t", t=topic)
        else:
            rows = await self.db.fetch(self._RATING)
        return [self._rating(row) for row in rows]

    async def close(self) -> None:
        await self.db.close()


def build(url: str) -> AccountStore:
    """The server's database URL, or `memory://`."""
    from norboten_api.db import is_postgres

    return PostgresAccountStore(url) if is_postgres(url) else MemoryAccountStore()
