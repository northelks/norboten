"""A real session going live is announced on Telegram once; a sample one, or no bot, never."""

import httpx

from norboten_api import announce
from norboten_api.play_store import PlaySession
from norboten_api.settings import settings


def _session(**over) -> PlaySession:
    fields = {
        "session_id": "session-one",
        "user_id": "u1",
        "nick": "tux",
        "country": "PL",
        "lab_id": "linux-01-disk-full",
        "lab_title": "The Disk That Stays Full",
        "width": 120,
        "height": 32,
    }
    return PlaySession(**(fields | over))


def _capture(monkeypatch, status: int = 200) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json={"ok": status == 200})

    real = httpx.AsyncClient
    monkeypatch.setattr(
        announce.httpx,
        "AsyncClient",
        lambda **kw: real(transport=httpx.MockTransport(handler), **kw),
    )
    return seen


async def test_a_live_session_is_announced(monkeypatch):
    monkeypatch.setattr(settings(), "telegram_bot_token", "123:abc")
    monkeypatch.setattr(settings(), "telegram_chat", "@norboten")
    seen = _capture(monkeypatch)
    assert await announce.live_session(_session()) is True
    assert str(seen[0].url) == "https://api.telegram.org/bot123:abc/sendMessage"
    body = seen[0].read().decode()
    assert "tux is working on The Disk That Stays Full right now." in body


async def test_sample_sessions_and_a_missing_bot_say_nothing(monkeypatch):
    seen = _capture(monkeypatch)
    assert await announce.live_session(_session()) is False  # no token configured
    monkeypatch.setattr(settings(), "telegram_bot_token", "123:abc")
    monkeypatch.setattr(settings(), "telegram_chat", "@norboten")
    assert await announce.live_session(_session(seed=True)) is False
    assert seen == []


async def test_a_failing_telegram_is_logged_not_raised(monkeypatch, caplog):
    monkeypatch.setattr(settings(), "telegram_bot_token", "123:secret")
    monkeypatch.setattr(settings(), "telegram_chat", "@norboten")
    _capture(monkeypatch, status=500)
    assert await announce.live_session(_session()) is False
    assert "secret" not in caplog.text


def test_starting_a_session_schedules_the_announcement(client, monkeypatch):
    told = []

    async def fake(session):
        told.append(session.nick)
        return True

    monkeypatch.setattr(announce, "live_session", fake)
    headers = {"X-Debug-User": "u-live"}
    assert client.post("/me", json={"nick": "livetux", "country": "PL"}, headers=headers).is_success
    body = {"lab_id": "hello", "width": 80, "height": 24}
    assert client.post("/play/sessions", json=body, headers=headers).status_code == 201
    assert told == ["livetux"]
