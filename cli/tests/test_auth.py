"""Signing in from the terminal: GitHub's device flow, remembering the machine, and the file."""

import stat
import time

import pytest

from norboten import auth


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("NORBOTEN_HOME", str(tmp_path))
    monkeypatch.delenv("NORBOTEN_DEBUG_USER", raising=False)
    monkeypatch.setattr(auth, "_session", None)


class _Response:
    def __init__(self, status: int, payload: dict | None = None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


def _creds(**over) -> auth.Credentials:
    return auth.Credentials(**({"access_token": "at", "expires_at": time.time() + 3600} | over))


def test_credentials_are_written_for_the_owner_only():
    auth.save(_creds())
    path = auth.credentials_path()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert auth.load().access_token == "at"


def test_a_damaged_credentials_file_is_not_fatal():
    auth.credentials_path().parent.mkdir(parents=True, exist_ok=True)
    auth.credentials_path().write_text("{ not json")
    assert auth.load() is None
    assert auth.token() is None


def test_an_expired_token_is_not_used():
    auth.save(_creds(expires_at=time.time() - 1))
    assert auth.token() is None


def test_headers_fall_back_to_the_debug_identity(monkeypatch):
    assert auth.headers() == {}
    monkeypatch.setenv("NORBOTEN_DEBUG_USER", "user-1")
    assert auth.headers() == {"X-Debug-User": "user-1"}
    auth.save(_creds())
    assert auth.headers() == {"Authorization": "Bearer at"}  # a real token wins


def test_signing_out_revokes_on_the_server_and_forgets_here(monkeypatch):
    calls = []
    monkeypatch.setattr(
        auth.httpx, "post", lambda url, **kw: calls.append((url, kw)) or _Response(200)
    )
    auth.save(_creds())
    assert auth.forget() is True
    assert calls[0][0].endswith("/auth/logout")
    assert calls[0][1]["headers"] == {"Authorization": "Bearer at"}
    assert auth.load() is None
    assert auth.forget() is False


class _Server:
    """The two sign-in endpoints, answering from a script; remembers every body it was sent."""

    def __init__(self, **replies):
        self.replies = {path: list(answers) for path, answers in replies.items()}
        self.sent = []

    def __call__(self, url, json=None, timeout=None, headers=None):
        path = "/" + url.split("://", 1)[1].split("/", 1)[1]
        self.sent.append((path, json))
        return self.replies[path].pop(0)


def _token(expires_in=7_776_000):
    return _Response(200, {"access_token": "cli-token", "expires_in": expires_in})


def _started():
    return _Response(
        200,
        {
            "poll_id": "poll-handle-1",
            "user_code": "WDJB-MJHT",
            "verification_uri": "https://github.com/login/device",
            "interval": 5,
            "expires_in": 900,
        },
    )


def test_a_remembered_sign_in_writes_the_token_for_the_owner_only(monkeypatch):
    server = _Server(
        **{
            "/auth/github/device": [_started()],
            "/auth/github/poll": [
                _Response(428, {"detail": "waiting for GitHub", "interval": 5}),
                _Response(429, {"detail": "slow down", "interval": 10}),
                _token(),
            ],
        }
    )
    monkeypatch.setattr(auth.httpx, "post", server)
    started = auth.start(remember=True)
    assert (started.user_code, started.verification_uri) == (
        "WDJB-MJHT",
        "https://github.com/login/device",
    )
    assert server.sent[0][1]["label"] and server.sent[0][1]["remember"] is True
    assert auth.poll(started.poll_id, remember=True) == auth.Waiting(5)
    assert auth.poll(started.poll_id, remember=True) == auth.Waiting(10)
    creds = auth.poll(started.poll_id, remember=True)

    assert creds.access_token == "cli-token" and not creds.expired
    assert auth.load().access_token == "cli-token"
    assert stat.S_IMODE(auth.credentials_path().stat().st_mode) == 0o600
    assert server.sent[-1][1] == {"poll_id": "poll-handle-1", "remember": True}


def test_an_unremembered_sign_in_never_touches_the_disk(monkeypatch):
    auth.save(_creds(access_token="old-remembered"))  # a stale file must not win afterwards
    server = _Server(**{"/auth/github/poll": [_token(12 * 3600)]})
    monkeypatch.setattr(auth.httpx, "post", server)
    auth.poll("poll-handle-1", remember=False)

    assert not auth.credentials_path().exists()
    assert auth.token() == "cli-token" and auth.headers() == {"Authorization": "Bearer cli-token"}
    monkeypatch.setattr(auth.httpx, "post", lambda *a, **k: _Response(200))
    assert auth.forget() is True and auth.token() is None


@pytest.mark.parametrize(
    ("status", "detail"), [(403, "denied on GitHub"), (410, "the code expired")]
)
def test_a_denied_or_expired_sign_in_says_what_the_server_said(monkeypatch, status, detail):
    over = _Response(status, {"detail": detail})
    monkeypatch.setattr(auth.httpx, "post", _Server(**{"/auth/github/poll": [over]}))
    with pytest.raises(auth.LoginError, match=detail) as caught:
        auth.poll("poll-handle-1", remember=True)
    assert caught.value.status == status and auth.token() is None


def test_a_server_without_sign_in_says_so(monkeypatch):
    monkeypatch.setattr(auth.httpx, "post", _Server(**{"/auth/github/device": [_Response(503)]}))
    with pytest.raises(auth.LoginError, match="not configured"):
        auth.start(remember=True)
