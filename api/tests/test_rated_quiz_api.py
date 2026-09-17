"""Rated theory through the real app: served one at a time, graded on the server's clock."""

from __future__ import annotations

import json
import shutil
import time

import pytest

from norboten.paths import repo_root
from norboten.quiz.bank import load
from norboten_api import deps
from norboten_api.routers import rated_quiz
from norboten_api.settings import settings

HEAD = {"X-Debug-User": "quiz-1"}
OTHER = {"X-Debug-User": "quiz-2"}
SOURCE = repo_root() / "quizzes" / "bash.yaml"


@pytest.fixture
def bank(tmp_path, monkeypatch):
    folder = tmp_path / "rated" / "quizzes"
    folder.mkdir(parents=True)
    shutil.copy(SOURCE, folder / "bash.yaml")
    monkeypatch.setenv("NORBOTEN_RATED_DIR", str(tmp_path / "rated"))
    settings.cache_clear()
    deps.rated_banks.cache_clear()
    yield {q.id: q for q in load(SOURCE).bank.questions}
    deps.rated_banks.cache_clear()


@pytest.fixture
def player(client, bank):
    for head, nick in ((HEAD, "quizzer"), (OTHER, "other")):
        assert client.post("/me", json={"nick": nick, "country": "PL"}, headers=head).is_success
    return client


def _run(client, questions, *, right: bool = True, head=HEAD) -> dict:
    r = client.post("/rated/quiz/sessions", json={"topic": "bash"}, headers=head)
    assert r.status_code == 201, r.text
    started = r.json()
    sid, q = started["session_id"], started["question"]
    last = {}
    for i in range(started["total"]):
        if i:
            q = client.post(f"/rated/quiz/sessions/{sid}/next", headers=head).json()["question"]
        key = questions[q["id"]].answer
        wrong = [c["id"] for c in q["choices"] if c["id"] not in key][:1]
        body = {"question_id": q["id"], "selected": list(key) if right else wrong}
        last = client.post(f"/rated/quiz/sessions/{sid}/answers", json=body, headers=head).json()
        assert last["correct"] is right
    return last | {"session_id": sid}


def test_a_question_goes_out_without_its_answer(player, bank) -> None:
    banks = player.get("/rated/quiz/banks", headers=HEAD).json()
    assert [b["topic"] for b in banks] == ["bash"] and banks[0]["questions"] <= 10
    started = player.post("/rated/quiz/sessions", json={"topic": "bash"}, headers=HEAD).json()
    q = started["question"]
    assert set(q) == {
        "id", "type", "difficulty", "prompt", "code", "code_lang", "choices", "time_limit_seconds"
    }  # fmt: skip
    assert bank[q["id"]].explanation not in json.dumps(started)


def test_a_right_run_is_graded_here_and_rated(player, bank) -> None:
    done = _run(player, bank)
    assert done["finished"] and done["outcome"] == "passed" and done["score_percent"] == 100
    assert done["rating_delta"] and all(d > 0 for d in done["rating_delta"].values())
    assert done["explanation"] and done["references"]
    history = player.get("/me", headers=HEAD).json()["history"]
    assert history[0]["kind"] == "quiz" and history[0]["rated"] is True
    closed = player.post(f"/rated/quiz/sessions/{done['session_id']}/next", headers=HEAD)
    assert closed.status_code == 410


def test_a_wrong_run_loses(player, bank) -> None:
    done = _run(player, bank, right=False)
    assert done["outcome"] == "failed" and all(d < 0 for d in done["rating_delta"].values())


def test_the_server_clock_decides_what_is_late(player, bank, monkeypatch) -> None:
    started = player.post("/rated/quiz/sessions", json={"topic": "bash"}, headers=HEAD).json()
    q = started["question"]
    later = time.time() + q["time_limit_seconds"] + rated_quiz.NETWORK_GRACE + 1
    monkeypatch.setattr(rated_quiz.time, "time", lambda: later)
    body = {"question_id": q["id"], "selected": list(bank[q["id"]].answer)}
    got = player.post(
        f"/rated/quiz/sessions/{started['session_id']}/answers", json=body, headers=HEAD
    ).json()
    assert got["expired"] and not got["correct"]


def test_one_question_at_a_time_and_only_your_own(player, bank) -> None:
    started = player.post("/rated/quiz/sessions", json={"topic": "bash"}, headers=HEAD).json()
    sid, q = started["session_id"], started["question"]
    url = f"/rated/quiz/sessions/{sid}"
    assert player.post(f"{url}/next", headers=HEAD).status_code == 409  # not answered yet
    other_q = next(i for i in bank if i != q["id"])
    body = {"question_id": other_q, "selected": ["a"]}
    assert player.post(f"{url}/answers", json=body, headers=HEAD).status_code == 409
    mine = {"question_id": q["id"], "selected": ["a"]}
    assert player.post(f"{url}/answers", json=mine, headers=OTHER).status_code == 404
    assert player.post(f"{url}/answers", json=mine, headers=HEAD).status_code == 200
    assert player.post(f"{url}/answers", json=mine, headers=HEAD).status_code == 409  # twice


def test_leaving_a_run_counts_what_was_seen(player, bank) -> None:
    first = player.post("/rated/quiz/sessions", json={"topic": "bash"}, headers=HEAD).json()
    player.post("/rated/quiz/sessions", json={"topic": "bash"}, headers=HEAD)
    view = player.get("/me", headers=HEAD).json()["history"][0]
    assert view["kind"] == "quiz" and view["passed"] is False and view["score_percent"] == 0
    assert first["session_id"]


async def test_an_abandoned_run_expires(player, bank) -> None:
    player.post("/rated/quiz/sessions", json={"topic": "bash"}, headers=HEAD)
    state = player.app.state
    assert await rated_quiz.expire(state.accounts, state.rated_quiz, now=time.time() + 7200) == 1


def test_no_rated_banks_without_rated_content(client, monkeypatch) -> None:
    monkeypatch.delenv("NORBOTEN_RATED_DIR", raising=False)
    settings.cache_clear()
    deps.rated_banks.cache_clear()
    client.post("/me", json={"nick": "plainq", "country": "PL"}, headers=HEAD)
    assert client.get("/rated/quiz/banks", headers=HEAD).json() == []
    assert (
        client.post("/rated/quiz/sessions", json={"topic": "bash"}, headers=HEAD).status_code == 404
    )
