"""Accounts: what an attempt does to a rating, and what a profile adds up to."""

import time
from datetime import UTC, date, datetime, timedelta

import pytest

from norboten_api import accounts as acc
from norboten_api import rating as rt
from norboten_api.account_store import MemoryAccountStore, NickTaken, build

DAY = 86400
TODAY = date(2026, 9, 12)
NOON = datetime(2026, 9, 12, 12, tzinfo=UTC).timestamp()


def _attempt(**over) -> acc.Attempt:
    data = {
        "user_id": "u1",
        "lab_id": "rhcsa-03",
        "started_at": NOON,
        "duration_seconds": 600,
        "score_percent": 100,
        "passed": True,
        "rated": True,
        "difficulty": 3,
        "topics": ["storage-lvm", "boot-systemd"],
    }
    return acc.Attempt.model_validate(data | over)


def test_a_rated_attempt_is_one_game_per_topic():
    after = acc.rate(_attempt(), {})
    assert set(after) == {"storage-lvm", "boot-systemd"}
    assert all(r.games == 1 and r.r > rt.BASE_RATING for r in after.values())


def test_practice_does_not_rate():
    assert acc.rate(_attempt(rated=False), {}) == {}


def test_the_clock_decides_the_result():
    won = acc.rate(_attempt(), {})["storage-lvm"]
    lost = acc.rate(_attempt(within_limit=False), {})["storage-lvm"]
    assert lost.r < rt.BASE_RATING < won.r


def test_deltas_are_measured_from_a_fresh_rating():
    after = acc.rate(_attempt(), {})
    d = acc.deltas({}, after)
    assert d["storage-lvm"] == round(after["storage-lvm"].r - rt.BASE_RATING, 2)


def test_overall_leans_on_the_topics_you_have_actually_played():
    ratings = {
        "bash": acc.TopicRating(user_id="u1", topic="bash", r=1800, rd=60, games=20),
        "python": acc.TopicRating(user_id="u1", topic="python", r=1200, rd=300, games=1),
    }
    combined = acc.overall(ratings)
    assert 1700 < combined.r < 1800  # the well-played topic dominates
    assert combined.rd < 60  # and two topics know more than one


def test_overall_of_a_new_account_is_the_base_rating():
    assert acc.overall({}) == rt.Rating()


def test_the_radar_always_has_every_spoke():
    spokes = acc.radar(acc.rate(_attempt(), {}))
    assert len(spokes) == 19
    played = [s for s in spokes if s["games"]]
    assert {s["topic"] for s in played} == {"storage-lvm", "boot-systemd"}
    assert all(s["rating"] is None for s in spokes if not s["games"])


def test_contributions_count_days_not_attempts():
    attempts = [
        _attempt(started_at=NOON),
        _attempt(started_at=NOON - 60),
        _attempt(started_at=NOON - DAY),
        _attempt(started_at=NOON - 5 * DAY),
    ]
    heat = acc.contributions(attempts, today=TODAY)
    assert heat["days"]["2026-09-12"] == 2
    assert heat["total"] == 4
    assert heat["best_day"] == 2
    assert heat["streak"] == 2  # today and yesterday; the five-day-old one is not adjacent


def test_a_streak_survives_an_empty_today():
    yesterday = NOON - DAY
    heat = acc.contributions([_attempt(started_at=yesterday)], today=TODAY)
    assert heat["streak"] == 1


def test_contributions_ignore_what_falls_outside_the_window():
    old = _attempt(started_at=NOON - 400 * DAY)
    assert acc.contributions([old], today=TODAY)["total"] == 0


def test_a_nick_must_look_like_a_handle():
    with pytest.raises(ValueError):
        acc.User(user_id="u1", nick="Ihar", country="PL")
    with pytest.raises(ValueError):
        acc.User(user_id="u1", nick="ab", country="PL")
    with pytest.raises(ValueError):
        acc.User(user_id="u1", nick="ihar", country="pol")


def test_the_avatar_survives_a_rename():
    user = acc.User(user_id="u1", nick="ihar", country="PL")
    assert user.avatar_seed == user.model_copy(update={"nick": "northelks"}).avatar_seed


# -- the store ---------------------------------------------------------------------------------


@pytest.fixture
def store():
    return MemoryAccountStore()


async def test_a_nick_belongs_to_one_account(store):
    await store.put_user(acc.User(user_id="u1", nick="ihar", country="PL"))
    with pytest.raises(NickTaken):
        await store.put_user(acc.User(user_id="u2", nick="ihar", country="CA"))


async def test_renaming_frees_the_old_nick(store):
    await store.put_user(acc.User(user_id="u1", nick="ihar", country="PL"))
    await store.put_user(acc.User(user_id="u1", nick="northelks", country="PL"))
    assert await store.user_by_nick("ihar") is None
    assert (await store.user_by_nick("northelks")).user_id == "u1"


async def test_attempts_come_back_newest_first(store):
    for i in range(3):
        await store.add_attempt(_attempt(started_at=NOON - i * DAY, lab_id=f"lab-{i}"))
    got = await store.attempts("u1")
    assert [a.lab_id for a in got] == ["lab-0", "lab-1", "lab-2"]


async def test_ratings_round_trip_per_topic(store):
    after = acc.rate(_attempt(), {})
    await store.put_ratings(list(after.values()))
    held = await store.ratings("u1")
    assert set(held) == set(after)
    assert held["storage-lvm"].r == after["storage-lvm"].r
    assert [r.topic for r in await store.all_ratings("bash")] == []


async def test_a_second_attempt_builds_on_the_first(store):
    first = acc.rate(_attempt(), {})
    await store.put_ratings(list(first.values()))
    second = acc.rate(_attempt(started_at=time.time()), await store.ratings("u1"))
    assert second["storage-lvm"].games == 2
    assert second["storage-lvm"].rd < first["storage-lvm"].rd


def test_the_url_picks_the_backend():
    from norboten_api.account_store import PostgresAccountStore

    assert isinstance(build("memory://"), MemoryAccountStore)
    assert isinstance(build("postgresql://norboten@db/norboten"), PostgresAccountStore)
    assert isinstance(build("postgres://norboten@db/norboten"), PostgresAccountStore)


def test_a_day_is_read_in_utc():
    just_before_midnight = datetime(2026, 9, 12, 23, 59, tzinfo=UTC).timestamp()
    assert _attempt(started_at=just_before_midnight).day == TODAY
    assert _attempt(started_at=just_before_midnight + 120).day == TODAY + timedelta(days=1)
