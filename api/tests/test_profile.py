"""The signed-in half of the API, through the real app."""

import json
import time

import pytest

HEAD = {"X-Debug-User": "user-1"}
OTHER = {"X-Debug-User": "user-2"}


@pytest.fixture
def signed_up(client):
    r = client.post("/me", json={"nick": "ihar", "country": "PL"}, headers=HEAD)
    assert r.status_code == 201, r.text
    return r.json()


def test_a_profile_needs_a_nick_first(client):
    assert client.get("/me", headers=HEAD).status_code == 404


def test_signing_up_and_reading_yourself(client, signed_up):
    me = client.get("/me", headers=HEAD).json()
    assert me["user"]["nick"] == "ihar"
    assert me["overall"]["rating"] == 1500
    assert me["overall"]["provisional"] is True
    assert len(me["radar"]) == 19
    assert me["attempts"] == 0


def test_a_nick_is_claimed_once(client, signed_up):
    clash = client.post("/me", json={"nick": "ihar", "country": "CA"}, headers=OTHER)
    assert clash.status_code == 409


def test_the_nick_is_chosen_once_and_the_country_can_change(client, signed_up):
    renamed = client.post("/me", json={"nick": "northelks", "country": "PL"}, headers=HEAD)
    assert renamed.status_code == 409 and renamed.json()["detail"] == "the nick is chosen once"
    moved = client.post("/me", json={"country": "DE"}, headers=HEAD)
    assert moved.status_code == 201 and moved.json()["nick"] == "ihar"
    same = client.post("/me", json={"nick": "ihar", "country": "FR"}, headers=HEAD)
    assert same.status_code == 201
    assert client.get("/profile/ihar").json()["user"]["country"] == "FR"
    assert client.get("/profile/northelks").status_code == 404
    assert same.json()["avatar_seed"] == signed_up["avatar_seed"]


def test_a_profile_needs_a_nick_to_begin_with(client):
    assert client.post("/me", json={"country": "PL"}, headers=HEAD).status_code == 422


def test_an_unauthenticated_call_is_refused(client):
    assert client.get("/me").status_code == 401


def test_recording_an_attempt_never_rates_it(client, signed_up):
    """Only a rated lab moves the board: an unrated lab's answer is public, so a reported pass
    proves nothing (docs/lab-spec.md §12). The attempt is still on the profile."""
    body = {
        "lab_id": "rhcsa-03-storage-and-lvm",
        "started_at": time.time() - 600,
        "duration_seconds": 600,
        "score_percent": 100,
        "passed": True,
        "rated": True,  # what an older client sends for R; ignored
    }
    r = client.post("/attempts", json=body, headers=HEAD)
    assert r.status_code == 201, r.text
    got = r.json()
    assert got["rated"] is False and got["rating_delta"] == {}
    assert got["within_limit"] is True
    me = client.get("/me", headers=HEAD).json()
    assert me["attempts"] == 1 and me["passed"] == 1
    assert me["contributions"]["total"] == 1
    assert me["overall"]["rating"] == 1500
    assert not [s for s in me["radar"] if s["games"]]
    assert me["history"][0]["rated"] is False


def test_the_server_decides_the_difficulty_and_the_clock(client, signed_up):
    """A client cannot claim it finished in time, or name its own topics."""
    body = {
        "lab_id": "rhcsa-03-storage-and-lvm",
        "started_at": time.time() - 9000,
        "duration_seconds": 9000,  # far past the lab's limit
        "score_percent": 100,
        "passed": True,
        "difficulty": 1,
        "topics": ["bash"],
    }
    got = client.post("/attempts", json=body, headers=HEAD).json()
    assert got["within_limit"] is False


def test_a_quiz_attempt_must_name_its_topics(client, signed_up):
    body = {
        "lab_id": "bash",
        "kind": "quiz",
        "started_at": time.time(),
        "duration_seconds": 45,
        "score_percent": 80,
        "passed": True,
    }
    assert client.post("/attempts", json=body, headers=HEAD).status_code == 422
    ok = client.post("/attempts", json=body | {"difficulty": 2, "topics": ["bash"]}, headers=HEAD)
    assert ok.status_code == 201
    assert ok.json()["rating_delta"] == {}


def _rated_win(client, user_id: str) -> None:
    """A rated attempt as the rated router settles one, without the machine."""
    from norboten_api import accounts as acc
    from norboten_api.routers.profile import settle

    attempt = acc.Attempt(
        user_id=user_id,
        lab_id="linux-90-rated-example",
        started_at=time.time(),
        duration_seconds=60,
        score_percent=100,
        passed=True,
        rated=True,
        difficulty=3,
        topics=["storage-lvm", "boot-systemd"],
    )
    client.portal.call(settle, client.app.state.accounts, attempt)


def test_the_board_sorts_on_the_conservative_rating(client, signed_up):
    client.post("/me", json={"nick": "ada", "country": "CA"}, headers=OTHER)
    for _ in range(6):
        _rated_win(client, "user-1")
    _rated_win(client, "user-2")

    board = client.get("/leaderboard").json()
    assert [row["nick"] for row in board] == ["ihar", "ada"]
    assert board[0]["rank"] == 1
    assert board[0]["conservative"] > board[1]["conservative"]

    per_topic = client.get("/leaderboard", params={"topic": "bash"}).json()
    assert per_topic == []


def test_a_profile_is_public_but_the_history_is_the_owners(client, signed_up):
    client.post(
        "/attempts",
        json={
            "lab_id": "hello",
            "started_at": time.time(),
            "duration_seconds": 120,
            "score_percent": 100,
            "passed": True,
        },
        headers=HEAD,
    )
    public = client.get("/profile/ihar").json()
    assert public["user"]["nick"] == "ihar"
    assert public["history"][0]["lab_id"] == "hello"
    assert "user_id" not in public["user"]


def test_the_board_is_cached_briefly(client):
    first = client.get("/leaderboard").json()
    bus = client.app.state.bus
    import asyncio

    cached = asyncio.run(bus.get("board:overall:50"))
    assert cached is not None and json.loads(cached) == first


def test_the_country_is_guessed_offline_and_never_stored(client, tmp_path, monkeypatch):
    from norboten_api import geo
    from norboten_api.settings import settings

    csv = tmp_path / "dbip.csv"
    csv.write_text(
        "1.0.0.0,1.0.0.255,AU\n31.0.0.0,31.0.255.255,PL\n2a00::,2a00:ffff:ffff:ffff:ffff:ffff:ffff:ffff,DE\n"
    )
    assert geo.build(csv, tmp_path / "country.bin") == 3
    monkeypatch.setattr(settings(), "geo_db", str(tmp_path / "country.bin"))
    geo.table.cache_clear()
    try:
        for address, country in [("31.0.12.34", "PL"), ("2a00::1", "DE"), ("9.9.9.9", "")]:
            got = client.get("/geo/country", headers={"X-Forwarded-For": address})
            assert got.json() == {"country": country}, address
        assert client.get("/geo/country", headers={"X-Forwarded-For": "10.1.2.3"}).json() == {
            "country": ""
        }
        # a guess is only an answer: no profile, no row
        assert client.get("/me", headers=HEAD).status_code == 404
    finally:
        geo.table.cache_clear()


def test_without_a_table_the_guess_is_empty(client, monkeypatch):
    from norboten_api import geo
    from norboten_api.settings import settings

    monkeypatch.setattr(settings(), "geo_db", "/nonexistent/country.bin")
    geo.table.cache_clear()
    assert client.get("/geo/country").json() == {"country": ""}
    geo.table.cache_clear()


def test_deleting_the_account_takes_the_work_and_frees_the_nick(client, signed_up):
    client.post(
        "/attempts",
        json={
            "lab_id": "hello",
            "started_at": time.time() - 300,
            "duration_seconds": 300,
            "score_percent": 100,
            "passed": True,
        },
        headers=HEAD,
    )
    assert client.get("/me", headers=HEAD).json()["attempts"] == 1
    assert client.get("/profile/ihar").status_code == 200

    assert client.request("DELETE", "/me", headers=HEAD).status_code == 204

    assert client.get("/me", headers=HEAD).status_code == 404  # no profile, no attempts, no rating
    assert client.get("/profile/ihar").status_code == 404  # gone from the board too
    # and the nick is free: someone else may take it
    taken_again = client.post("/me", json={"nick": "ihar", "country": "CA"}, headers=OTHER)
    assert taken_again.status_code == 201, taken_again.text


def test_deleting_ends_the_session_that_asked(client, sign_in):
    body = sign_in("tux")
    headers = {"Authorization": f"Bearer {body['token']}"}
    client.post("/me", json={"nick": "tux", "country": "PL"}, headers=headers)
    assert client.request("DELETE", "/me", headers=headers).status_code == 204
    # the token went with the account: the same request is now a stranger's
    assert client.get("/me", headers=headers).status_code == 401
    assert client.request("DELETE", "/me", headers=headers).status_code == 401


def test_an_account_without_a_nick_can_still_be_deleted(client):
    assert client.get("/me", headers=HEAD).status_code == 404
    assert client.request("DELETE", "/me", headers=HEAD).status_code == 204


def test_deleting_needs_a_caller(client):
    from norboten_api.settings import settings

    settings().require_auth = True
    try:
        assert client.request("DELETE", "/me").status_code == 401
    finally:
        settings().require_auth = False
