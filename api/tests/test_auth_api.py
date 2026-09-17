"""Accounts this server owns: a GitHub identity, the tokens it issues, and nothing else.

GitHub is the stub in `oauth_stubs.py`, reached in-process; every GitHub answer the device flow
can give is driven through it.
"""

import pytest

from norboten_api.settings import settings


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _start(client, **body):
    r = client.post("/auth/github/device", json={"label": "laptop (Linux)"} | body)
    assert r.status_code == 200, r.text
    return r.json()


def _poll(client, poll_id: str, **extra):
    return client.post("/auth/github/poll", json={"poll_id": poll_id} | extra)


# -- a terminal: the device flow -----------------------------------------------------------------


def test_the_first_sign_in_makes_the_account_and_the_second_finds_it(client, sign_in):
    body = sign_in("tux", github_id=1001)
    assert body["new_account"] is True and body["github_login"] == "tux"
    headers = _bearer(body["token"])
    assert client.get("/me", headers=headers).status_code == 404  # no nick yet, but known
    made = client.post("/me", json={"nick": "tux", "country": "PL"}, headers=headers)
    assert made.status_code == 201
    again = sign_in("tux", github_id=1001)
    assert again["new_account"] is False and again["user_id"] == body["user_id"]


def test_a_renamed_github_login_is_the_same_account_with_the_new_login(client, sign_in):
    first = sign_in("old-name", github_id=77)
    renamed = sign_in("new-name", github_id=77)
    assert renamed["user_id"] == first["user_id"]
    me = client.get("/auth/me", headers=_bearer(renamed["token"])).json()
    assert me["github_login"] == "new-name" and me["github_id"] == 77


def test_the_terminal_sees_the_user_code_and_never_githubs_device_code(client, github):
    started = _start(client)
    assert started["user_code"] == "WDJB-MJHT"
    assert started["verification_uri"] == "https://github.com/login/device"
    assert set(started) == {"poll_id", "user_code", "verification_uri", "interval", "expires_in"}
    assert "dev-" not in str(started)


def test_every_github_answer_while_polling(client, github):
    github.device_answers = ["authorization_pending", "slow_down", "authorization_pending", "token"]
    poll_id = _start(client)["poll_id"]
    waiting = _poll(client, poll_id)
    assert waiting.status_code == 428 and waiting.json()["interval"] == 5
    slower = _poll(client, poll_id)
    assert slower.status_code == 429 and slower.json()["interval"] == 10
    assert _poll(client, poll_id).json()["interval"] == 10  # the new interval is kept
    done = _poll(client, poll_id, remember=False)
    assert done.status_code == 200 and done.json()["expires_in"] == 12 * 3600
    assert _poll(client, poll_id).status_code == 410  # one sign-in per flow


@pytest.mark.parametrize(
    ("answer", "status", "words"),
    [("expired_token", 410, "expired"), ("access_denied", 403, "denied on GitHub")],
)
def test_an_expired_or_denied_code_ends_the_flow(client, github, answer, status, words):
    github.device_answers = [answer]
    poll_id = _start(client)["poll_id"]
    r = _poll(client, poll_id)
    assert r.status_code == status and words in r.json()["detail"]
    assert _poll(client, poll_id).status_code == 410


def test_the_github_token_is_revoked_and_stored_nowhere(client, sign_in, github):
    body = sign_in("tux")
    issued = list(github.tokens)
    assert issued and github.revoked == issued
    state = client.app.state
    stored = str(state.credentials._accounts) + str(state.credentials._tokens)
    assert all(t not in stored for t in issued)
    assert body["token"] not in state.credentials._tokens  # only its hash
    assert all(len(key) == 64 for key in state.credentials._tokens)


def test_remembering_decides_how_long_the_token_lives(client, sign_in):
    assert sign_in("tux", remember=True)["expires_in"] == 90 * 24 * 3600
    assert sign_in("tux", remember=False)["expires_in"] == 12 * 3600


def test_a_terminal_says_which_machine_it_is(client, sign_in):
    body = sign_in("tux", label="laptop (Linux)")
    listed = client.get("/auth/tokens", headers=_bearer(body["token"])).json()
    assert [(t["kind"], t["label"]) for t in listed] == [("cli", "laptop (Linux)")]


def test_an_unknown_poll_handle_is_410(client, github):
    assert _poll(client, "not-a-real-handle").status_code == 410


# -- the site: the web flow ----------------------------------------------------------------------


STATE = "page-state-0123456789abcdef"


def _go(client, **params):
    query = {"state": STATE, "remember": "true", "return": "account"} | params
    return client.get("/auth/github/go", params=query, follow_redirects=False)


def _through_github(client, github, go):
    """What the browser does: follow to GitHub, which approves, and back to the callback."""
    from urllib.parse import parse_qs, urlsplit

    to_github = urlsplit(go.headers["location"])
    query = {k: v[0] for k, v in parse_qs(to_github.query).items()}
    assert query["client_id"] == "Iv1.stub" and "scope" not in query
    code = f"code-{len(github.codes) + 1}"
    github.codes[code] = dict(github.user)
    return client.get(
        "/auth/github/callback",
        params={"code": code, "state": query["state"]},
        follow_redirects=False,
    )


def _fragment(location: str) -> dict:
    from urllib.parse import parse_qs

    return {k: v[0] for k, v in parse_qs(location.split("#", 1)[1]).items()}


def test_the_web_flow_ends_with_a_one_time_code_in_the_fragment(client, github):
    back = _through_github(client, github, _go(client))
    assert back.status_code == 302 and back.headers["location"].startswith(
        f"{settings().site_url}/account/#"
    )
    fragment = _fragment(back.headers["location"])
    assert fragment["state"] == STATE and "token" not in back.headers["location"]
    got = client.post("/auth/github/exchange", json={"once": fragment["once"]})
    assert got.status_code == 200 and got.json()["github_login"] == "Tux-Penguin"
    assert got.json()["expires_in"] == 90 * 24 * 3600
    assert (
        client.get("/auth/tokens", headers=_bearer(got.json()["token"])).json()[0]["kind"] == "web"
    )
    assert github.revoked  # the GitHub token went at once


def test_a_one_time_code_works_once_and_not_late(client, github, monkeypatch):
    once = _fragment(_through_github(client, github, _go(client)).headers["location"])["once"]
    assert client.post("/auth/github/exchange", json={"once": once}).status_code == 200
    assert client.post("/auth/github/exchange", json={"once": once}).status_code == 410

    from norboten_api import pending

    monkeypatch.setattr(pending, "ONCE_SECONDS", -1)
    from norboten_api.routers import auth

    monkeypatch.setattr(auth, "ONCE_SECONDS", -1)
    late = _fragment(_through_github(client, github, _go(client)).headers["location"])["once"]
    assert client.post("/auth/github/exchange", json={"once": late}).status_code == 410


def test_a_callback_with_a_state_this_server_never_issued_is_refused(client, github):
    r = client.get(
        "/auth/github/callback",
        params={"code": "anything", "state": "forged-state-value"},
        follow_redirects=False,
    )
    assert r.status_code == 302 and r.headers["location"].endswith("#error=expired")
    # and a real flow's state works only once
    go = _go(client)
    assert "once=" in _through_github(client, github, go).headers["location"]
    assert "#error=expired" in _through_github(client, github, go).headers["location"]


def test_denied_on_github_goes_back_with_the_reason(client, github):
    from urllib.parse import parse_qs, urlsplit

    go = _go(client, **{"return": "authorize:request-abc-123"})
    state = parse_qs(urlsplit(go.headers["location"]).query)["state"][0]
    r = client.get(
        "/auth/github/callback",
        params={"error": "access_denied", "state": state},
        follow_redirects=False,
    )
    assert r.headers["location"] == (
        f"{settings().site_url}/authorize/?request=request-abc-123#error=denied"
    )


@pytest.mark.parametrize("target", ["https://evil.example/", "authorize:", "account/../x"])
def test_the_return_target_is_only_ever_this_sites_pages(client, github, target):
    assert _go(client, **{"return": target}).status_code == 422


# -- a deployment without an OAuth app -----------------------------------------------------------


def test_without_github_keys_nobody_can_sign_in_and_it_says_so(client):
    r = client.post("/auth/github/device", json={"label": "x"})
    assert r.status_code == 503 and "not configured" in r.json()["detail"]
    assert client.post("/auth/github/poll", json={"poll_id": "whatever-handle"}).status_code == 503
    go = client.get(
        "/auth/github/go", params={"state": STATE, "return": "account"}, follow_redirects=False
    )
    assert go.headers["location"].endswith("#error=not-configured")
    assert client.get("/auth/config").json() == {
        "mode": "github",
        "github": False,
        "discord": False,
        "account_uri": f"{settings().site_url}/account/",
    }


def test_the_old_ways_in_are_gone(client):
    for path in (
        "/auth/code",
        "/auth/code/verify",
        "/auth/register",
        "/auth/login",
        "/auth/device",
    ):
        assert client.post(path, json={}).status_code == 404, path


# -- tokens ---------------------------------------------------------------------------------------


def test_signing_out_revokes_the_token(client, sign_in):
    headers = _bearer(sign_in("tux")["token"])
    assert client.post("/auth/logout", headers=headers).status_code == 200
    assert client.get("/me", headers=headers).status_code == 401


def test_an_unknown_token_is_401_not_a_debug_user(client):
    r = client.get("/me", headers=_bearer("made-up") | {"X-Debug-User": "someone"})
    assert r.status_code == 401


def test_require_auth_refuses_the_debug_header(client, monkeypatch):
    monkeypatch.setattr(settings(), "require_auth", True)
    assert client.get("/me", headers={"X-Debug-User": "someone"}).status_code == 401


def test_one_client_cannot_start_sign_ins_without_end(client, github, monkeypatch):
    monkeypatch.setenv("NORBOTEN_SIGN_INS_PER_MINUTE", "3")
    settings.cache_clear()
    statuses = [
        client.post("/auth/github/device", json={"label": "x"}).status_code for _ in range(4)
    ]
    assert statuses == [200, 200, 200, 429]
