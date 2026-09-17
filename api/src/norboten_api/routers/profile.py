"""Signed-in identity: the profile, the attempts that rate it, and the board they sort on.

This is the authenticated half of the API. `/progress` stays as it is — anonymous, opt-in, no
account — so nobody is forced to sign in to use Norboten on their own machine.
"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from norboten_api import accounts as acc
from norboten_api import geo
from norboten_api.account_store import AccountStore, NickTaken
from norboten_api.auth import Caller, caller, current_user, get_accounts, get_credentials
from norboten_api.credentials import CredentialStore
from norboten_api.deps import client_key, get_bus, lab_or_none
from norboten_api.live import Bus

BOARD_CACHE_SECONDS = 30

router = APIRouter(tags=["profile"])


class SignUp(BaseModel):
    #: Chosen once. Required to make a profile; afterwards it may be left out, or repeated as it is.
    nick: str | None = Field(default=None, pattern=acc.NICK_PATTERN)
    country: str = Field(pattern=acc.COUNTRY_PATTERN)


class AttemptIn(BaseModel):
    """What the CLI reports when a lab (or a timed quiz) ends."""

    lab_id: str
    kind: acc.AttemptKind = "lab"
    started_at: float
    duration_seconds: int = Field(ge=0)
    score_percent: int = Field(ge=0, le=100)
    passed: bool
    rated: bool = False  # ignored: see record_attempt
    difficulty: int | None = Field(default=None, ge=1, le=5)
    topics: list[str] | None = None


def _public(user: acc.User, github_login: str = "") -> dict:
    return {
        "nick": user.nick,
        "country": user.country,
        "avatar_seed": user.avatar_seed,
        "created_at": user.created_at,
        "seed": user.seed,
        # the GitHub account behind the profile, linked from it; empty for a sample account
        "github_login": github_login,
    }


def _rating_view(value) -> dict:
    return {
        "rating": round(value.r),
        "rd": round(value.rd),
        "provisional": value.provisional,
        "conservative": round(value.conservative),
    }


@router.post("/me", status_code=201)
async def sign_up(
    body: SignUp,
    who: Caller = Depends(caller),
    accounts: AccountStore = Depends(get_accounts),
) -> dict:
    """Make the profile: a nick, chosen once, and a country. After that the country is the one
    thing that changes — a different nick is 409 "the nick is chosen once"."""
    existing = await accounts.user(who.user_id)
    if existing is None and body.nick is None:
        raise HTTPException(422, "choose a nick to make a profile")
    if existing is not None and body.nick not in (None, existing.nick):
        raise HTTPException(409, "the nick is chosen once")
    user = acc.User(
        user_id=who.user_id,
        nick=existing.nick if existing else body.nick,
        country=body.country,
        created_at=existing.created_at if existing else time.time(),
    )
    try:
        await accounts.put_user(user)
    except NickTaken:
        raise HTTPException(409, f"the nick {user.nick!r} is taken") from None
    return _public(user)


@router.get("/geo/country")
async def guess_country(request: Request) -> dict:
    """The country this request probably comes from, to pre-fill a form — `{"country": "PL"}`, or
    `""` when the address is unknown or private. Looked up offline (`geo.py`, DB-IP Lite); nothing
    is sent anywhere and nothing is stored."""
    return {"country": geo.country(client_key(request))}


@router.get("/me")
async def me(
    user: acc.User = Depends(current_user),
    accounts: AccountStore = Depends(get_accounts),
    credentials: CredentialStore = Depends(get_credentials),
) -> dict:
    """The signed-in account's profile: nick, country, overall and per-topic ratings, a year of
    contributions and recent attempts. 404 until a nick is chosen.
    """
    return await _profile(user, accounts, credentials)


@router.get("/profile/{nick}")
async def profile(
    nick: str,
    accounts: AccountStore = Depends(get_accounts),
    credentials: CredentialStore = Depends(get_credentials),
) -> dict:
    """Anyone's public profile by nick, in the same shape as `/me`, with the GitHub account it
    signs in with."""
    user = await accounts.user_by_nick(nick)
    if user is None:
        raise HTTPException(404, "no such profile")
    return await _profile(user, accounts, credentials)


async def _profile(user: acc.User, accounts: AccountStore, credentials: CredentialStore) -> dict:
    ratings = await accounts.ratings(user.user_id)
    attempts = await accounts.attempts(user.user_id)
    github_login = (await credentials.github_logins([user.user_id])).get(user.user_id, "")
    return {
        "user": _public(user, github_login),
        "overall": _rating_view(acc.overall(ratings)),
        "radar": acc.radar(ratings),
        "contributions": acc.contributions(attempts),
        "history": [
            a.model_dump(include={"lab_id", "kind", "started_at", "duration_seconds"})
            | {"passed": a.passed, "score_percent": a.score_percent, "rated": a.rated}
            | {"rating_delta": a.rating_delta}
            for a in attempts[:50]
        ],
        "attempts": len(attempts),
        "passed": sum(1 for a in attempts if a.passed),
    }


@router.post("/attempts", status_code=201)
async def record_attempt(
    body: AttemptIn,
    who: Caller = Depends(caller),
    accounts: AccountStore = Depends(get_accounts),
) -> dict:
    """Record an attempt on the profile. It never moves a rating: only a rated lab or rated theory,
    graded on this server (`/rated`), does — an unrated lab's checks and answer are public, so a
    reported pass proves nothing. `rated` in the body is accepted from older clients and ignored.
    The server still decides the difficulty, topics and clock, which the profile shows."""
    user = await accounts.user(who.user_id)
    if user is None:
        raise HTTPException(404, "no profile yet: POST /me to choose a nick")

    difficulty, topics = body.difficulty, body.topics
    lab = lab_or_none(body.lab_id) if body.kind == "lab" else None
    if lab is not None:
        difficulty = lab.manifest.difficulty
        topics = list(lab.manifest.topics)
        within_limit = body.duration_seconds <= lab.manifest.rated_minutes * 60
    else:
        if difficulty is None or not topics:
            raise HTTPException(422, "unknown lab: difficulty and topics are required")
        within_limit = True

    attempt = acc.Attempt(
        user_id=user.user_id,
        kind=body.kind,
        lab_id=body.lab_id,
        started_at=body.started_at,
        duration_seconds=body.duration_seconds,
        score_percent=body.score_percent,
        passed=body.passed,
        rated=False,
        within_limit=within_limit,
        difficulty=difficulty,
        topics=topics,
    )
    attempt, overall = await settle(accounts, attempt)
    return {
        "rated": attempt.rated,
        "within_limit": attempt.within_limit,
        "rating_delta": attempt.rating_delta,
        "overall": overall,
    }


async def settle(accounts: AccountStore, attempt: acc.Attempt) -> tuple[acc.Attempt, dict]:
    """Store an attempt and apply it to the ratings: the attempt with its deltas, and the overall
    rating that follows. The one place an attempt turns into a rating change."""
    before = await accounts.ratings(attempt.user_id)
    after = acc.rate(attempt, before)
    attempt = attempt.model_copy(update={"rating_delta": acc.deltas(before, after)})
    await accounts.add_attempt(attempt)
    await accounts.put_ratings(list(after.values()))
    return attempt, _rating_view(acc.overall(before | after))


@router.get("/leaderboard")
async def leaderboard(
    topic: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    accounts: AccountStore = Depends(get_accounts),
    bus: Bus = Depends(get_bus),
) -> list[dict]:
    """Sorted on the conservative rating, so a lucky first win does not top the board. Cached for
    thirty seconds: every profile page and TUI screen asks, and it changes one attempt at a time."""
    key = f"board:{topic or 'overall'}:{limit}"
    cached = await bus.get(key)
    if cached is not None:
        return json.loads(cached)
    rows = await accounts.all_ratings(topic)
    if topic:
        best = {r.user_id: r for r in rows}
        scored = [(u, r.value) for u, r in best.items()]
    else:
        by_user: dict[str, dict[str, acc.TopicRating]] = {}
        for r in rows:
            by_user.setdefault(r.user_id, {})[r.topic] = r
        scored = [(u, acc.overall(rs)) for u, rs in by_user.items()]

    scored.sort(key=lambda pair: pair[1].conservative, reverse=True)
    scored = scored[:limit]
    users = await accounts.users([u for u, _ in scored])
    board = [
        {"rank": i, **_public(users[u]), **_rating_view(v)}
        for i, (u, v) in enumerate(scored, start=1)
        if u in users
    ]
    await bus.set(key, json.dumps(board), ttl=BOARD_CACHE_SECONDS)
    return board
