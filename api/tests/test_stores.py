"""Every store behaves the same in memory and in PostgreSQL.

The memory variants always run. The PostgreSQL ones run when NORBOTEN_TEST_DATABASE_URL points at
a database they may wipe — CI starts one as a service, and locally `make test-db` does.
"""

import os
import time
import uuid

import pytest

from norboten_api import account_store, play_store, rated_store
from norboten_api.accounts import Attempt, TopicRating, User
from norboten_api.play_store import FrameBatch, PlaySession

PG = os.environ.get("NORBOTEN_TEST_DATABASE_URL", "")
KINDS = ["memory", pytest.param("postgres", marks=pytest.mark.skipif(not PG, reason="no test db"))]


async def _wipe(url: str) -> None:
    from sqlalchemy import text

    from norboten_api import db

    await db.apply_schema(url)
    async with db.engine(url).begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE events, users, credentials, tokens, pending_sign_ins, attempts, ratings, "
                "play_sessions, play_batches, rated_attempts, rated_quiz_sessions"
            )
        )


@pytest.fixture(params=KINDS)
async def url(request):
    if request.param == "memory":
        yield "memory://"
        return
    await _wipe(PG)
    yield PG
    from norboten_api import db

    await db.engine(PG).dispose()
    db.engine.cache_clear()


def _user(nick: str, **kw) -> User:
    return User(user_id=kw.pop("user_id", uuid.uuid4().hex), nick=nick, country="PL", **kw)


# -- accounts ------------------------------------------------------------------------------------


async def test_users_round_trip_and_nicks_are_unique(url):
    s = account_store.build(url)
    await s.setup()
    a = _user("tux", created_at=1_700_000_000.5)
    await s.put_user(a)
    assert await s.user(a.user_id) == a
    assert (await s.user_by_nick("tux")).user_id == a.user_id
    with pytest.raises(account_store.NickTaken):
        await s.put_user(_user("tux"))
    renamed = a.model_copy(update={"nick": "penguin"})
    await s.put_user(renamed)
    assert await s.user_by_nick("tux") is None
    assert (await s.users([a.user_id, "nobody"])) == {a.user_id: renamed}
    await s.close()


async def test_attempts_come_back_newest_first(url):
    s = account_store.build(url)
    await s.setup()
    u = _user("reader")
    await s.put_user(u)
    for n in range(3):
        await s.add_attempt(
            Attempt(
                user_id=u.user_id,
                lab_id=f"lab-{n}",
                started_at=1_700_000_000 + n * 60,
                duration_seconds=100 + n,
                score_percent=50 + n,
                passed=n == 2,
                rated=True,
                difficulty=2,
                topics=["storage-lvm", "boot-systemd"],
                rating_delta={"storage-lvm": 12.5},
            )
        )
    got = await s.attempts(u.user_id, limit=2)
    assert [a.lab_id for a in got] == ["lab-2", "lab-1"]
    assert got[0].topics == ["storage-lvm", "boot-systemd"]
    assert got[0].rating_delta == {"storage-lvm": 12.5}
    assert got[0].started_at == 1_700_000_120
    await s.close()


async def test_ratings_upsert_and_the_board_reads_them(url):
    s = account_store.build(url)
    await s.setup()
    u = _user("rated")
    await s.put_user(u)
    await s.put_ratings(
        [TopicRating(user_id=u.user_id, topic="networking", r=1600, rd=80, games=3)]
    )
    await s.put_ratings(
        [TopicRating(user_id=u.user_id, topic="networking", r=1650, rd=70, games=4)]
    )
    await s.put_ratings([TopicRating(user_id=u.user_id, topic="bash", r=1400, rd=200, games=1)])
    mine = await s.ratings(u.user_id)
    assert mine["networking"].r == 1650 and mine["networking"].games == 4
    assert {r.topic for r in await s.all_ratings()} == {"networking", "bash"}
    assert [r.topic for r in await s.all_ratings("bash")] == ["bash"]
    await s.close()


# -- play ----------------------------------------------------------------------------------------


def _session(**kw) -> PlaySession:
    return PlaySession(
        session_id=uuid.uuid4().hex,
        user_id="u1",
        nick="tux",
        lab_id="hello",
        width=100,
        height=28,
        **kw,
    )


async def test_a_session_records_batches_and_ends(url):
    s = play_store.build(url)
    await s.setup()
    session = _session()
    await s.start(session)
    assert [x.session_id for x in await s.live()] == [session.session_id]
    for seq in range(2):
        updated = await s.append(
            session.session_id,
            FrameBatch(
                seq=seq,
                at=seq * 2.0,
                events=[[seq * 2.0, "o", "$ ls\r\n"], [seq * 2.0 + 0.1, "o", "x\r\n"]],
                commands=[{"at": seq * 2.0, "text": "ls"}],
                changes=[{"path": "/etc/x", "diff": "+a", "command": "ls"}] if seq else [],
            ),
        )
        assert updated.frames == 2 * (seq + 1) and updated.commands == seq + 1
    assert [b.seq for b in await s.batches(session.session_id, after=0)] == [1]
    await s.end(session.session_id, passed=True)
    ended = await s.session(session.session_id)
    assert ended.ended_at is not None and ended.passed is True
    assert await s.append(session.session_id, FrameBatch(seq=9, at=0)) is None
    assert await s.live() == []
    assert [x.session_id for x in await s.recent()] == [session.session_id]
    await s.close()


async def test_old_recordings_are_purged(url):
    s = play_store.build(url)
    await s.setup()
    old = _session(started_at=time.time() - play_store.RETENTION_SECONDS - 60)
    new = _session()
    await s.start(old)
    await s.start(new)
    assert await s.purge() == 1
    assert await s.session(old.session_id) is None
    assert await s.session(new.session_id) is not None
    await s.close()


# -- credentials ---------------------------------------------------------------------------------


async def test_credentials_and_tokens(url):
    from norboten_api import credentials as creds

    s = creds.build(url)
    await s.setup()
    # the first sign-in with a GitHub id makes the account; the next signs the same one in, and a
    # renamed login is brought up to date
    user_id, made = await s.ensure_github(583231, "octocat")
    assert made is True
    assert await s.ensure_github(583231, "octo-renamed") == (user_id, False)
    me = await s.identity(user_id)
    assert (me.github_id, me.github_login, me.discord_id, me.digest) == (
        583231,
        "octo-renamed",
        None,
        False,
    )
    other, made = await s.ensure_github(42, "someone")
    assert made is True and other != user_id
    assert await s.github_logins([user_id, other, "nobody"]) == {
        user_id: "octo-renamed",
        other: "someone",
    }

    await s.add_token("secret-token", user_id, "cli", ttl=3600, label="laptop")
    await s.add_token("stale-token", user_id, "web", ttl=-1)
    assert await s.user_for("secret-token") == user_id
    assert await s.user_for("stale-token") is None
    assert [(t["kind"], t["label"]) for t in await s.tokens(user_id)] == [("cli", "laptop")]
    await s.revoke("secret-token")
    assert await s.user_for("secret-token") is None

    # the digest is a Discord DM: only a linked account with it on is a subscriber
    assert await s.digest_subscribers() == []
    await s.set_digest(user_id, True)
    assert await s.digest_subscribers() == []
    await s.link_discord(user_id, "80351110224678912")
    assert await s.digest_subscribers() == [creds.Subscriber(user_id, "80351110224678912")]
    with pytest.raises(creds.DiscordTaken):
        await s.link_discord(other, "80351110224678912")
    await s.set_discord_error(user_id, "closed")
    assert (await s.identity(user_id)).discord_error == "closed"
    await s.unlink_discord(user_id)
    me = await s.identity(user_id)
    assert (me.discord_id, me.digest, me.discord_error) == (None, False, "")
    assert await s.digest_subscribers() == []
    await s.close()


async def test_a_pending_sign_in_is_used_once_and_expires(url):
    from norboten_api import pending

    s = pending.build(url)
    await s.setup()
    flow = await s.create("device", {"device_code": "dev-1", "interval": 5})
    assert (await s.get(flow, "device")).data == {"device_code": "dev-1", "interval": 5}
    assert await s.get(flow, "web") is None  # a handle is only good for its own kind
    await s.update(flow, {"device_code": "dev-1", "interval": 10})
    assert (await s.get(flow, "device")).data["interval"] == 10
    assert (await s.take(flow, "device")).data["device_code"] == "dev-1"
    assert await s.take(flow, "device") is None  # once

    late = await s.create("once", {"github_id": 1}, ttl=-1)
    assert await s.get(late, "once") is None and await s.take(late, "once") is None
    await s.close()


async def test_rated_attempts_round_trip_and_expire(url):
    store = rated_store.build(url)
    await store.setup()
    now = time.time()
    attempt = rated_store.RatedAttempt(
        attempt_id=uuid.uuid4().hex,
        user_id="u-rated",
        lab_id="linux-90-rated-example",
        lab_version="1.0.0",
        image="ubuntu-26.04",
        nonce="n",
        key="ab" * 32,
        issued_at=now,
        expires_at=now + 60,
    )
    await store.put(attempt)
    assert [a.attempt_id for a in await store.open_for("u-rated")] == [attempt.attempt_id]
    assert await store.expired(now) == []
    assert [a.attempt_id for a in await store.expired(now + 120)] == [attempt.attempt_id]

    attempt.records["pre_reboot"] = rated_store.Received(record={"boot_id": "b1"}, received_at=now)
    attempt.outcome = "passed"
    attempt.checks = [rated_store.CheckVerdict(id="01_x", objective=1, passed=True)]
    await store.put(attempt)
    back = await store.get(attempt.attempt_id)
    assert back == attempt
    assert await store.open_for("u-rated") == []
    assert await store.expired(now + 120) == []
    assert await store.get("missing") is None
    await store.close()


async def test_rated_quiz_runs_round_trip(url):
    store = rated_store.build_quiz(url)
    await store.setup()
    now = time.time()
    run = rated_store.RatedQuizSession(
        attempt_id=uuid.uuid4().hex,
        user_id="u-quiz",
        topic="bash",
        issued_at=now,
        expires_at=now + 60,
        order=["bash-001", "bash-002"],
        served=[rated_store.ServedQuestion(id="bash-001", asked_at=now)],
    )
    await store.put(run)
    assert [r.attempt_id for r in await store.open_for("u-quiz")] == [run.attempt_id]
    run.served[0].selected = ["a"]
    run.outcome = "failed"
    await store.put(run)
    assert await store.get(run.attempt_id) == run
    assert await store.open_for("u-quiz") == []
    await store.close()
