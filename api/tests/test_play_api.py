"""Live and replayed terminals, through the real app."""

import json

import pytest

HEAD = {"X-Debug-User": "user-1"}
OTHER = {"X-Debug-User": "user-2"}


@pytest.fixture
def signed_up(client):
    assert client.post("/me", json={"nick": "ihar", "country": "PL"}, headers=HEAD).status_code
    return client


@pytest.fixture
def session_id(client, signed_up):
    r = client.post(
        "/play/sessions",
        json={"lab_id": "rhcsa-03-storage-and-lvm", "width": 100, "height": 30},
        headers=HEAD,
    )
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def _batch(seq: int, text: str, command: str | None = None) -> dict:
    return {
        "seq": seq,
        "at": float(seq),
        "events": [[float(seq), "o", text]],
        "commands": [{"at": float(seq), "text": command}] if command else [],
        "changes": [],
    }


def test_you_cannot_stream_without_a_profile(client):
    r = client.post(
        "/play/sessions", json={"lab_id": "hello", "width": 80, "height": 24}, headers=HEAD
    )
    assert r.status_code == 404


def test_a_session_appears_on_the_live_list(client, session_id):
    client.post(f"/play/sessions/{session_id}/frames", json=_batch(0, "hi"), headers=HEAD)
    live = client.get("/play/live").json()
    assert [s["session_id"] for s in live["live"]] == [session_id]
    card = live["live"][0]
    from norboten_api.deps import lab_or_none

    assert card["nick"] == "ihar"
    assert card["lab_title"] == lab_or_none("rhcsa-03-storage-and-lvm").manifest.title
    assert card["live"] is True and card["frames"] == 1


def test_only_the_owner_may_append(client, session_id):
    r = client.post(f"/play/sessions/{session_id}/frames", json=_batch(0, "x"), headers=OTHER)
    assert r.status_code == 403


def test_a_recording_reads_back_as_asciicast(client, session_id):
    client.post(f"/play/sessions/{session_id}/frames", json=_batch(0, "$ ls\n", "ls"), headers=HEAD)
    client.post(f"/play/sessions/{session_id}/frames", json=_batch(1, "etc\n"), headers=HEAD)
    client.post(f"/play/sessions/{session_id}/end", json={"passed": True}, headers=HEAD)

    got = client.get(f"/play/sessions/{session_id}").json()
    assert got["header"]["version"] == 2
    assert got["header"]["width"] == 100
    assert [e[2] for e in got["events"]] == ["$ ls\n", "etc\n"]
    assert [c["text"] for c in got["commands"]] == ["ls"]
    assert got["session"]["passed"] is True
    assert got["session"]["live"] is False


def test_a_finished_session_moves_to_recent(client, session_id):
    client.post(f"/play/sessions/{session_id}/frames", json=_batch(0, "x"), headers=HEAD)
    client.post(f"/play/sessions/{session_id}/end", json={}, headers=HEAD)
    live = client.get("/play/live").json()
    assert live["live"] == []
    assert [s["session_id"] for s in live["recent"]] == [session_id]


def test_appending_to_a_finished_session_is_refused(client, session_id):
    client.post(f"/play/sessions/{session_id}/end", json={}, headers=HEAD)
    r = client.post(f"/play/sessions/{session_id}/frames", json=_batch(0, "x"), headers=HEAD)
    assert r.status_code == 409


def test_the_stream_sends_the_header_then_the_batches(client, session_id):
    client.post(f"/play/sessions/{session_id}/frames", json=_batch(0, "first", "ls"), headers=HEAD)
    client.post(f"/play/sessions/{session_id}/frames", json=_batch(1, "second"), headers=HEAD)
    client.post(f"/play/sessions/{session_id}/end", json={}, headers=HEAD)

    with client.stream("GET", f"/play/sessions/{session_id}/stream") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())

    events = [chunk for chunk in body.split("\n\n") if chunk.strip()]
    kinds = [
        line.split("event: ")[1]
        for chunk in events
        for line in chunk.splitlines()
        if line.startswith("event: ")
    ]
    assert kinds == ["header", "batch", "batch", "end"]
    payloads = [json.loads(chunk.split("data: ")[1]) for chunk in events]
    assert payloads[0]["width"] == 100
    assert payloads[1]["events"][0][2] == "first"
    assert payloads[2]["events"][0][2] == "second"


def test_the_stream_can_resume_after_a_sequence(client, session_id):
    for seq in range(3):
        client.post(
            f"/play/sessions/{session_id}/frames", json=_batch(seq, f"line{seq}"), headers=HEAD
        )
    client.post(f"/play/sessions/{session_id}/end", json={}, headers=HEAD)

    with client.stream("GET", f"/play/sessions/{session_id}/stream?after=0") as r:
        body = "".join(r.iter_text())
    assert "line0" not in body  # already seen
    assert "line1" in body and "line2" in body


def test_a_viewer_sees_who_they_are_watching(client, session_id):
    got = client.get("/play/leaderboard-context/ihar").json()
    assert got["nick"] == "ihar" and got["country"] == "PL"
    assert got["rating"] == 1500 and got["provisional"] is True
    assert client.get("/play/leaderboard-context/nobody").status_code == 404


def test_an_unknown_session_is_a_404(client):
    assert client.get("/play/sessions/nope").status_code == 404
    assert client.get("/play/sessions/nope/stream").status_code == 404
