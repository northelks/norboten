"""The MCP server and the OAuth that lets a client read an account's own progress.

The API runs for real, under uvicorn on a free port, and the official MCP client (protocol
2026-07-28, stateless) talks to it; the OAuth flow is driven by hand, step by step, the way a
client does it. Stores are in memory; the client's metadata document is served by the test.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import secrets
import socket
import threading
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import uvicorn
from mcp import Client
from mcp_types import ElicitResult
from oauth_stubs import GitHubState, github_stub

from norboten_api import github, mcp_server
from norboten_api.main import create_app
from norboten_api.routers import oauth
from norboten_api.settings import settings

CLIENT_ID = "https://client.example/mcp-client.json"
REDIRECT = "http://127.0.0.1:33418/callback"
PUBLIC = {"search_docs", "list_labs", "get_lab", "list_topics", "quiz_me", "leaderboard"}


#: GitHub, answered in-process by the stub: the server runs in this process, so a patch reaches it.
GITHUB = GitHubState()


def sign_in(api: str, login: str = "tux") -> str:
    """A token for this GitHub login, the way a terminal gets one: start, GitHub approves, poll."""
    GITHUB.user = {"id": 5000 + sum(map(ord, login)), "login": login}
    GITHUB.polls = 0
    started = httpx.post(f"{api}/auth/github/device", json={"label": "tests"})
    assert started.status_code == 200, started.text
    got = httpx.post(
        f"{api}/auth/github/poll", json={"poll_id": started.json()["poll_id"], "remember": True}
    )
    assert got.status_code == 200, got.text
    return got.json()["token"]


def _port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def api(monkeypatch):
    """The whole API, listening. Yields its base URL."""
    port = _port()
    base = f"http://127.0.0.1:{port}"
    monkeypatch.setattr(github, "transport", httpx.ASGITransport(github_stub(GITHUB)))
    monkeypatch.setenv("NORBOTEN_GITHUB_CLIENT_ID", "Iv1.stub")
    monkeypatch.setenv("NORBOTEN_GITHUB_CLIENT_SECRET", "stub-secret")
    monkeypatch.setenv("NORBOTEN_GITHUB_URL", "http://github.stub")
    monkeypatch.setenv("NORBOTEN_GITHUB_API_URL", "http://github.stub")
    monkeypatch.setenv("NORBOTEN_API_URL", base)
    monkeypatch.setenv("NORBOTEN_SITE_URL", "https://site.example")
    monkeypatch.setenv("NORBOTEN_MCP_PER_MINUTE", "1000")
    settings.cache_clear()
    server = uvicorn.Server(uvicorn.Config(create_app(), port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    yield base
    server.should_exit = True
    thread.join(10)
    settings.cache_clear()


def run(coro):
    return asyncio.run(coro)


async def _tools(url: str, **kwargs):
    async with Client(url, **kwargs) as client:
        return await client.list_tools()


def _call(url: str, name: str, args: dict | None = None, **kwargs):
    async def go():
        async with Client(url, **kwargs) as client:
            return await client.call_tool(name, args or {})

    return run(go())


def _data(result) -> dict:
    assert not result.is_error, result.content
    return result.structured_content or json.loads(result.content[0].text)


def _raw(base: str, method: str, name: str = "", params: dict | None = None, token: str = ""):
    """One 2026-07-28 request by hand: a POST with the routing headers the protocol requires."""
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": method,
    }
    if name:
        headers["Mcp-Name"] = name
    if token:
        headers["Authorization"] = f"Bearer {token}"
    meta = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": (params or {}) | {"_meta": meta}}
    return httpx.post(f"{base}/mcp", json=body, headers=headers, timeout=10)


# -- public ---------------------------------------------------------------------------------------


def test_every_tool_is_listed_with_a_cache_hint(api):
    listed = run(_tools(f"{api}/mcp"))
    names = {t.name for t in listed.tools}
    assert names >= PUBLIC | mcp_server.PERSONAL | {"live_sessions"}
    assert listed.ttl_ms == mcp_server.LIST_TTL_MS
    assert all(t.annotations and t.annotations.read_only_hint for t in listed.tools)


def test_the_server_says_what_it_speaks_before_anything_else(api):
    found = _raw(api, "server/discover").json()["result"]
    assert "2026-07-28" in found["supportedVersions"]
    assert "tools" in found["capabilities"]


def test_search_finds_the_docs_and_says_it_is_data(api):
    found = _data(_call(f"{api}/mcp", "search_docs", {"query": "solvability gate reboot"}))
    assert found["note"] == mcp_server.NOTE
    assert found["results"] and found["results"][0]["url"].startswith("https://site.example/")


def test_a_lab_comes_with_two_hint_levels_and_never_its_solution(api):
    from norboten_api.deps import lab_or_none, solution_text

    lab = _data(_call(f"{api}/mcp", "get_lab", {"lab_id": "linux-01"}))
    text = json.dumps(lab)
    ladder = lab_or_none("linux-01").hints.checks["02_no_deleted_files_held_open"]
    assert " ".join(ladder.level_2.split()) in text
    assert " ".join(ladder.level_3.split()) not in text
    assert " ".join(ladder.level_4.split()) not in text
    assert not any(r.startswith("journal:linux-01") for c in lab["checks"] for r in c["reading"])
    for line in solution_text("linux-01").splitlines():
        if len(line.strip()) > 12 and not line.startswith("#"):
            assert line.strip() not in text


def test_the_guard_withholds_a_passage_that_carries_a_fix():
    from norboten_api.deps import solution_text

    line = next(
        ln.strip()
        for ln in solution_text("rhcsa-01").splitlines()
        if len(ln.strip()) > 12 and not ln.startswith("#")
    )
    assert mcp_server.guarded(f"a passage\n{line}\n").startswith("(withheld")
    assert mcp_server.guarded("a passage about groups") == "a passage about groups"


def test_quiz_me_asks_the_user_and_grades_the_answer(api):
    asked = []

    async def answer(ctx, params):
        asked.append(params.message)
        question = _find_question(params.message)
        return ElicitResult(action="accept", content={"answer": ",".join(question.answer)})

    result = _data(
        _call(f"{api}/mcp", "quiz_me", {"topic": "networking"}, elicitation_callback=answer)
    )
    assert len(asked) == 1, "one question, asked once, through input_required"
    assert result["correct"] is True and result["explanation"] and result["references"]


def test_quiz_me_without_elicitation_hands_the_question_to_the_model(api):
    first = _data(_call(f"{api}/mcp", "quiz_me", {"topic": "bash", "difficulty": 2}))
    assert "how_to_answer" in first and first["question"]
    graded = _data(
        _call(
            f"{api}/mcp",
            "quiz_me",
            {"topic": "bash", "question_id": first["question_id"], "answer": "z"},
        )
    )
    assert graded["correct"] is False and graded["correct_answer"]


def _find_question(message: str):
    from norboten.quiz import bank

    for loaded in bank.all_banks():
        for q in loaded.bank.questions:
            if q.prompt in message:
                return q
    raise AssertionError("the question shown is not in a bank")


def test_journals_are_resources_without_their_walkthrough(api):
    async def go():
        async with Client(f"{api}/mcp") as client:
            templates = await client.list_resource_templates()
            read = await client.read_resource("norboten://journal/linux-01-disk-full")
            return templates, read

    templates, read = run(go())
    uris = {t.uri_template for t in templates.resource_templates}
    assert uris == {"norboten://journal/{journal_id}", "norboten://lab/{lab_id}/briefing"}
    text = read.contents[0].text
    assert "## The mechanism" in text and "## A failure, walked through" not in text
    assert mcp_server.NOTE in text


def test_the_prompts_leave_the_fix_to_the_learner(api):
    async def go():
        async with Client(f"{api}/mcp") as client:
            return await client.get_prompt("explain_lab", {"lab_id": "hello"})

    prompt = run(go())
    text = prompt.messages[0].content.text
    assert "Do not name the fault or the fix" in text and 'untrusted="true"' in text


# -- the door -------------------------------------------------------------------------------------


def test_a_personal_tool_without_a_token_points_at_the_authorization_server(api):
    r = _raw(api, "tools/call", "my_progress", {"name": "my_progress", "arguments": {}})
    assert r.status_code == 401
    challenge = r.headers["www-authenticate"]
    assert f'resource_metadata="{api}/.well-known/oauth-protected-resource/mcp"' in challenge
    metadata = httpx.get(f"{api}/.well-known/oauth-protected-resource/mcp").json()
    assert metadata["resource"] == f"{api}/mcp"
    assert metadata["authorization_servers"] == [api]
    server = httpx.get(f"{api}/.well-known/oauth-authorization-server").json()
    assert server["issuer"] == api
    assert server["code_challenge_methods_supported"] == ["S256"]
    assert server["client_id_metadata_document_supported"] is True
    assert server["authorization_response_iss_parameter_supported"] is True
    assert "registration_endpoint" not in server


def test_a_token_for_the_rest_of_the_api_is_not_a_token_for_mcp(api):
    r = _raw(api, "tools/list", token=sign_in(api, "ab"))
    assert r.status_code == 401 and 'error="invalid_token"' in r.headers["www-authenticate"]


def test_public_calls_are_audited_and_rate_limited(api, monkeypatch):
    assert _raw(api, "tools/call", "list_topics", {"name": "list_topics"}).status_code == 200
    monkeypatch.setenv("NORBOTEN_MCP_PER_MINUTE", "2")
    settings.cache_clear()
    statuses = [_raw(api, "tools/list").status_code for _ in range(4)]
    assert 429 in statuses


# -- OAuth ----------------------------------------------------------------------------------------


@pytest.fixture
def metadata_document(monkeypatch):
    async def fetch(client_id: str) -> dict:
        assert client_id == CLIENT_ID
        return {"client_id": CLIENT_ID, "client_name": "A test client", "redirect_uris": [REDIRECT]}

    monkeypatch.setattr(oauth, "fetch_metadata", fetch)


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def _authorize(api: str, challenge: str, **extra) -> httpx.Response:
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT,
        "state": "xyz",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": "mcp",
        "resource": f"{api}/mcp",
    } | extra
    return httpx.get(f"{api}/oauth/authorize", params=params)


def _account(api: str) -> str:
    token = sign_in(api)
    headers = {"Authorization": f"Bearer {token}"}
    assert httpx.post(
        f"{api}/me", json={"nick": "tux", "country": "PL"}, headers=headers
    ).is_success
    return token


def _code(api: str, web_token: str, challenge: str) -> str:
    started = _authorize(api, challenge)
    assert started.status_code == 302
    consent = urlsplit(started.headers["location"])
    assert consent.netloc == "site.example" and consent.path == "/authorize/"
    request_id = parse_qs(consent.query)["request"][0]
    shown = httpx.get(f"{api}/oauth/requests/{request_id}").json()
    assert shown["client_name"] == "A test client" and shown["redirect_host"] == "127.0.0.1"
    decided = httpx.post(
        f"{api}/oauth/approve",
        json={"request": request_id, "allow": True},
        headers={"Authorization": f"Bearer {web_token}"},
    ).json()
    back = parse_qs(urlsplit(decided["redirect"]).query)
    assert back["state"] == ["xyz"] and back["iss"] == [api]  # RFC 9207
    return back["code"][0]


def _token(api: str, **form) -> httpx.Response:
    return httpx.post(f"{api}/oauth/token", data={"client_id": CLIENT_ID} | form)


def test_the_whole_flow_gives_a_token_that_reads_your_progress(api, metadata_document):
    web = _account(api)
    verifier, challenge = _pkce()
    code = _code(api, web, challenge)
    bad = _token(api, grant_type="authorization_code", code=code, redirect_uri=REDIRECT,
                 code_verifier="wrong" * 10)  # fmt: skip
    assert bad.status_code == 400 and bad.json()["error"] == "invalid_grant"
    # the failed attempt used the code up
    again = _token(api, grant_type="authorization_code", code=code, redirect_uri=REDIRECT,
                   code_verifier=verifier)  # fmt: skip
    assert again.json()["error"] == "invalid_grant"

    code = _code(api, web, challenge)
    issued = _token(api, grant_type="authorization_code", code=code, redirect_uri=REDIRECT,
                    code_verifier=verifier, resource=f"{api}/mcp")  # fmt: skip
    assert issued.status_code == 200, issued.text
    tokens = issued.json()
    assert tokens["token_type"] == "Bearer" and tokens["scope"] == "mcp"
    assert issued.headers["cache-control"] == "no-store"

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    progress = _call_with_token(api, "my_progress", tokens["access_token"])
    assert progress["nick"] == "tux"
    # its audience is the MCP server: the rest of the API refuses it
    assert httpx.get(f"{api}/me", headers=headers).status_code == 401

    rotated = _token(api, grant_type="refresh_token", refresh_token=tokens["refresh_token"])
    assert rotated.status_code == 200 and rotated.json()["access_token"] != tokens["access_token"]
    reused = _token(api, grant_type="refresh_token", refresh_token=tokens["refresh_token"])
    assert reused.json()["error"] == "invalid_grant"


def _call_with_token(api: str, name: str, token: str, args: dict | None = None) -> dict:
    r = _raw(api, "tools/call", name, {"name": name, "arguments": args or {}}, token=token)
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert not result.get("isError"), result
    return result.get("structuredContent") or json.loads(result["content"][0]["text"])


@pytest.mark.parametrize(
    ("extra", "error"),
    [
        ({"code_challenge_method": "plain"}, "invalid_request"),
        ({"scope": "mcp admin"}, "invalid_scope"),
        ({"resource": "https://elsewhere.example/mcp"}, "invalid_target"),
        ({"response_type": "token"}, "unsupported_response_type"),
    ],
)
def test_a_bad_request_goes_back_to_the_client_with_the_error(api, metadata_document, extra, error):
    _, challenge = _pkce()
    r = _authorize(api, challenge, **extra)
    assert r.status_code == 302
    back = parse_qs(urlsplit(r.headers["location"]).query)
    assert back["error"] == [error] and back["state"] == ["xyz"] and back["iss"] == [api]


def test_a_redirect_the_client_does_not_list_is_never_followed(api, metadata_document):
    _, challenge = _pkce()
    r = _authorize(api, challenge, redirect_uri="https://attacker.example/cb")
    assert r.status_code == 400 and "location" not in r.headers
    loopback = _authorize(api, challenge, redirect_uri="http://127.0.0.1:50999/callback")
    assert loopback.status_code == 302, "a loopback redirect may use any port (RFC 8252)"


def test_denying_sends_the_client_access_denied(api, metadata_document):
    web = _account(api)
    _, challenge = _pkce()
    started = _authorize(api, challenge)
    request_id = parse_qs(urlsplit(started.headers["location"]).query)["request"][0]
    decided = httpx.post(
        f"{api}/oauth/approve",
        json={"request": request_id, "allow": False},
        headers={"Authorization": f"Bearer {web}"},
    ).json()
    assert parse_qs(urlsplit(decided["redirect"]).query)["error"] == ["access_denied"]


def test_a_metadata_document_must_name_itself_and_be_https():
    for bad in ("http://client.example/doc.json", "file:///etc/passwd", "ftp://x/y"):
        with pytest.raises(oauth.ClientError):
            asyncio.run(oauth.fetch_metadata(bad))
    assert oauth.redirect_allowed("http://localhost:9/cb", ["http://localhost/cb"])
    assert not oauth.redirect_allowed("https://evil.example/cb", ["https://good.example/cb"])


def test_the_board_and_the_live_sessions_are_public(api):
    board = _data(_call(f"{api}/mcp", "leaderboard", {"limit": 3}))
    assert board["note"] == mcp_server.NOTE and isinstance(board["board"], list)
    live = _data(_call(f"{api}/mcp", "live_sessions", {}))
    assert set(live) >= {"live", "recent"}


def test_the_account_door_asks_for_a_token_before_anything(api):
    r = _raw(api, "tools/list", params={})
    assert r.status_code == 200
    legacy = httpx.post(
        f"{api}/mcp/account",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert legacy.status_code == 401
    assert "oauth-protected-resource/mcp/account" in legacy.headers["www-authenticate"]
    metadata = httpx.get(f"{api}/.well-known/oauth-protected-resource/mcp/account").json()
    assert metadata["resource"] == f"{api}/mcp/account"


def test_a_client_without_routing_headers_is_still_asked_to_sign_in(api):
    """Clients on revisions before 2026-07-28 send no Mcp-Name: the gate reads the body."""
    r = httpx.post(
        f"{api}/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "my_rating"}},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert r.status_code == 401 and "resource_metadata" in r.headers["www-authenticate"]
