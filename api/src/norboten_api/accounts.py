"""Accounts, attempts and what they add up to on a profile.

The models here are the contract between the CLI, the API and the site: who a learner is, what
they attempted, and the per-topic ratings that follow. The arithmetic lives in `rating`; this
module decides *which* games an attempt is worth and how nineteen topic ratings become one number.

Identity comes from Cognito — `user_id` is the token's `sub`, never something the client picks.
The nick is the public handle and is unique; the country is a flag on the profile and nothing else.
"""

from __future__ import annotations

import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from norboten import topics as taxonomy
from norboten_api import rating as rt

NICK_PATTERN = r"^[a-z0-9](?:[a-z0-9_-]{1,18}[a-z0-9])$"
COUNTRY_PATTERN = r"^[A-Z]{2}$"

AttemptKind = Literal["lab", "quiz"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class User(_Model):
    user_id: str = Field(min_length=1, max_length=128)
    nick: str = Field(pattern=NICK_PATTERN)
    country: str = Field(pattern=COUNTRY_PATTERN)
    created_at: float = Field(default_factory=time.time)
    seed: bool = False  # generated sample account, clearly marked everywhere it is shown

    @property
    def avatar_seed(self) -> str:
        """Identicons are drawn from the immutable id, so a rename keeps the same face."""
        return self.user_id


class Attempt(_Model):
    user_id: str
    kind: AttemptKind = "lab"
    lab_id: str  # the lab id, or the quiz topic for kind="quiz"
    started_at: float
    duration_seconds: int = Field(ge=0)
    score_percent: int = Field(ge=0, le=100)
    passed: bool
    rated: bool
    within_limit: bool = True
    difficulty: int = Field(ge=1, le=5)
    topics: list[str] = Field(min_length=1, max_length=5)
    rating_delta: dict[str, float] = Field(default_factory=dict)

    @property
    def day(self) -> date:
        return datetime.fromtimestamp(self.started_at, UTC).date()


class TopicRating(_Model):
    user_id: str
    topic: str
    r: float = rt.BASE_RATING
    rd: float = rt.BASE_RD
    sigma: float = rt.BASE_SIGMA
    games: int = 0
    updated_at: float = Field(default_factory=time.time)

    @property
    def value(self) -> rt.Rating:
        return rt.Rating(self.r, self.rd, self.sigma)

    @classmethod
    def of(cls, user_id: str, topic: str, value: rt.Rating, games: int) -> TopicRating:
        return cls(
            user_id=user_id,
            topic=topic,
            r=value.r,
            rd=value.rd,
            sigma=value.sigma,
            games=games,
            updated_at=time.time(),
        )


def rate(attempt: Attempt, current: dict[str, TopicRating]) -> dict[str, TopicRating]:
    """The topic ratings after this attempt. An unrated attempt changes nothing.

    A lab that declares three topics is three games, not a third of one: every topic it exercises
    was genuinely tested, and the deviation on each shrinks accordingly.
    """
    if not attempt.rated:
        return {}
    game = rt.game_for_attempt(
        attempt.difficulty, passed=attempt.passed, within_limit=attempt.within_limit
    )
    out: dict[str, TopicRating] = {}
    for topic in attempt.topics:
        held = current.get(topic) or TopicRating(user_id=attempt.user_id, topic=topic)
        out[topic] = TopicRating.of(
            attempt.user_id, topic, rt.update(held.value, [game]), held.games + 1
        )
    return out


def deltas(before: dict[str, TopicRating], after: dict[str, TopicRating]) -> dict[str, float]:
    out = {}
    for topic, new in after.items():
        old = before.get(topic)
        out[topic] = round(new.r - (old.r if old else rt.BASE_RATING), 2)
    return out


def overall(ratings: dict[str, TopicRating]) -> rt.Rating:
    """One number from many.

    Inverse-variance weighting: a topic you have played twenty times says more about you than one
    you have played twice, and the combined deviation shrinks only as far as the evidence allows.
    """
    played = [r for r in ratings.values() if r.games]
    if not played:
        return rt.Rating()
    weights = [1.0 / r.rd**2 for r in played]
    total = sum(weights)
    r = sum(w * x.r for w, x in zip(weights, played, strict=True)) / total
    return rt.Rating(r=round(r, 2), rd=round(min((1.0 / total) ** 0.5, rt.BASE_RD), 2))


def radar(ratings: dict[str, TopicRating]) -> list[dict]:
    """One spoke per taxonomy topic, in taxonomy order — including the ones never attempted."""
    out = []
    for topic in taxonomy.TOPICS:
        held = ratings.get(topic.slug)
        out.append(
            {
                "topic": topic.slug,
                "title": topic.title,
                "group": str(topic.group),
                "rating": held.r if held and held.games else None,
                "rd": held.rd if held and held.games else None,
                "games": held.games if held else 0,
            }
        )
    return out


def contributions(attempts: list[Attempt], *, days: int = 365, today: date | None = None) -> dict:
    """A GitHub-style heatmap: one cell per day, counting attempts.

    Returned as counts by ISO date plus the bounds, so the SVG can be drawn by the site without
    knowing anything about time zones.
    """
    end = today or datetime.now(UTC).date()
    start = end - timedelta(days=days - 1)
    counts = Counter(a.day for a in attempts if start <= a.day <= end)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": {d.isoformat(): n for d, n in sorted(counts.items())},
        "total": sum(counts.values()),
        "best_day": max(counts.values(), default=0),
        "streak": _streak(set(counts), end),
    }


def _streak(days: set[date], end: date) -> int:
    """Days in a row up to today (or up to yesterday, if today is still empty)."""
    cursor = end if end in days else end - timedelta(days=1)
    n = 0
    while cursor in days:
        n += 1
        cursor -= timedelta(days=1)
    return n
