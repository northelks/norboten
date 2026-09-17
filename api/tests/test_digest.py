"""The weekly digest: who gets one, what it says, and that it arrives as a Discord DM."""

import time
from urllib.parse import parse_qs, urlsplit

from norboten_api import digest
from norboten_api.settings import settings


def _account(client, sign_in, discord, login: str, nick: str | None, discord_id: str) -> dict:
    headers = {"Authorization": f"Bearer {sign_in(login)['token']}"}
    if nick:
        assert client.post("/me", json={"nick": nick, "country": "PL"}, headers=headers).is_success
    discord.user_id = discord_id
    start = client.post("/auth/discord/start", json={}, headers=headers).json()
    state = parse_qs(urlsplit(start["url"]).query)["state"][0]
    client.get("/auth/discord/callback", params={"code": "discord-code", "state": state})
    return headers


def _attempt(client, headers, lab_id: str, passed: bool, days_ago: float, **extra) -> None:
    body = {
        "lab_id": lab_id,
        "started_at": time.time() - days_ago * 86400,
        "duration_seconds": 600,
        "score_percent": 100 if passed else 40,
        "passed": passed,
        **extra,
    }
    assert client.post("/attempts", json=body, headers=headers).status_code == 201


async def _digests(client) -> list[digest.Digest]:
    state = client.app.state
    return await digest.digests(state.credentials, state.accounts, time.time())


async def test_the_digest_goes_only_to_those_who_asked_and_did_something(client, sign_in, discord):
    tux = _account(client, sign_in, discord, "tux", "tux", "d-tux")
    quiet = _account(client, sign_in, discord, "quiet", "quiet", "d-quiet")
    _account(client, sign_in, discord, "unasked", "unasked", "d-unasked")
    nameless = _account(client, sign_in, discord, "nameless", None, "d-nameless")

    assert client.get("/auth/preferences", headers=tux).json() == {"digest": False}
    for headers in (tux, quiet, nameless):
        assert client.put("/auth/preferences", json={"digest": True}, headers=headers).is_success

    _attempt(client, tux, "hello", True, 1)
    _attempt(client, tux, "linux-01-disk-full", False, 2)
    _attempt(client, tux, "hello", True, 20)  # not this week
    _attempt(client, quiet, "hello", True, 30)  # a quiet week

    items = await _digests(client)
    assert [(d.nick, d.discord_id) for d in items] == [("tux", "d-tux")]
    text = items[0].text
    assert text.startswith("**Your week on Norboten, tux.**")
    assert "2 attempts in the last seven days, 1 passed:" in text
    assert (
        "- lab: hello: passed, 100%" in text
        and "- lab: linux-01-disk-full: not passed, 40%" in text
    )
    # unrated labs are recorded and never rated, so there is no rating to report yet
    assert "Your overall rating is " not in text

    from norboten_api import accounts as acc
    from norboten_api.routers.profile import settle

    user = client.portal.call(client.app.state.accounts.user_by_nick, "tux")
    rated_win = acc.Attempt(
        user_id=user.user_id,
        lab_id="linux-90-rated-example",
        started_at=time.time() - 3600,
        duration_seconds=300,
        score_percent=100,
        passed=True,
        rated=True,
        difficulty=2,
        topics=["linux-basics"],
    )
    client.portal.call(settle, client.app.state.accounts, rated_win)
    text = (await _digests(client))[0].text
    assert "Your overall rating is " in text and "Next: " in text and "±" in text
    assert f"<{settings().site_url}/players/tux/>" in text

    client.put("/auth/preferences", json={"digest": False}, headers=tux)
    assert await _digests(client) == []


async def test_closed_dms_are_recorded_and_the_rest_still_go(client, sign_in, discord):
    closed = _account(client, sign_in, discord, "closed", "closed", "d-closed")
    slow = _account(client, sign_in, discord, "slow", "slow", "d-slow")
    for headers in (closed, slow):
        client.put("/auth/preferences", json={"digest": True}, headers=headers)
        _attempt(client, headers, "hello", True, 1)
    discord.closed = {"d-closed"}
    discord.rate_limited_once = {"d-slow"}  # a 429 is waited out

    state = client.app.state
    sent, failed = await digest.deliver(state.credentials, await _digests(client))
    assert (sent, failed) == (1, 1)
    assert [who for who, _ in discord.messages] == ["d-slow"]
    page = client.get("/auth/me", headers=closed).json()
    assert "allow direct messages" in page["discord"]["error"]


def test_preferences_need_a_signed_in_caller(client, monkeypatch):
    monkeypatch.setattr(settings(), "require_auth", True)
    assert client.get("/auth/preferences").status_code == 401
