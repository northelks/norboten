"""Discord: linking an account from its page, with and without joining, and the digest it enables.

Discord is the stub in `oauth_stubs.py`, reached in-process.
"""

from urllib.parse import parse_qs, urlsplit

from norboten_api.settings import settings


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _link(client, headers, join: bool):
    start = client.post("/auth/discord/start", json={"join": join}, headers=headers)
    assert start.status_code == 200, start.text
    query = {k: v[0] for k, v in parse_qs(urlsplit(start.json()["url"]).query).items()}
    return query, client.get(
        "/auth/discord/callback",
        params={"code": "discord-code", "state": query["state"]},
        follow_redirects=False,
    )


def test_linking_without_the_join_box_asks_only_who_you_are(client, sign_in, discord):
    headers = _bearer(sign_in("tux")["token"])
    query, back = _link(client, headers, join=False)
    assert query["scope"] == "identify"
    assert back.headers["location"] == f"{settings().site_url}/account/#discord=linked"
    assert discord.joined == []
    me = client.get("/auth/me", headers=headers).json()
    assert me["discord"] == {"available": True, "linked": True, "error": "", "invite": True}


def test_the_join_box_joins_the_norboten_server(client, sign_in, discord):
    headers = _bearer(sign_in("tux")["token"])
    query, back = _link(client, headers, join=True)
    assert query["scope"] == "identify guilds.join"
    assert back.headers["location"].endswith("#discord=joined")
    assert discord.joined == [("999", discord.user_id)]


def test_the_digest_needs_discord_and_unlinking_turns_it_off(client, sign_in, discord):
    headers = _bearer(sign_in("tux")["token"])
    refused = client.put("/auth/preferences", json={"digest": True}, headers=headers)
    assert refused.status_code == 409 and "Discord" in refused.json()["detail"]
    _link(client, headers, join=False)
    assert client.put("/auth/preferences", json={"digest": True}, headers=headers).is_success
    assert client.get("/auth/preferences", headers=headers).json() == {"digest": True}
    assert client.delete("/auth/discord", headers=headers).json() == {
        "linked": False,
        "digest": False,
    }
    assert client.get("/auth/me", headers=headers).json()["digest"] is False


def test_one_discord_user_links_one_account(client, sign_in, discord):
    _link(client, _bearer(sign_in("tux", github_id=1)["token"]), join=False)
    _, back = _link(client, _bearer(sign_in("other", github_id=2)["token"]), join=False)
    assert back.headers["location"].endswith("#discord=taken")


def test_a_callback_that_was_never_started_links_nothing(client, sign_in, discord):
    r = client.get(
        "/auth/discord/callback",
        params={"code": "discord-code", "state": "forged-state"},
        follow_redirects=False,
    )
    assert r.headers["location"].endswith("#discord=expired")


def test_without_discord_keys_the_page_is_told_there_is_nothing_to_link(client, sign_in):
    headers = _bearer(sign_in("tux")["token"])
    assert client.get("/auth/me", headers=headers).json()["discord"]["available"] is False
    assert client.post("/auth/discord/start", json={}, headers=headers).status_code == 503


def test_a_public_profile_links_its_github_account(client, sign_in):
    headers = _bearer(sign_in("Tux-Penguin")["token"])
    client.post("/me", json={"nick": "tux", "country": "PL"}, headers=headers)
    assert client.get("/profile/tux").json()["user"]["github_login"] == "Tux-Penguin"
    assert client.get("/me", headers=headers).json()["user"]["github_login"] == "Tux-Penguin"
