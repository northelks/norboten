"""One rated attempt end to end: the in-process API, a real container, the CLI's engine.

The API holds the rated lab; the engine asks it for an attempt, applies the faults it is sent,
collects the facts in the container, and the server judges. Nothing about the criteria is on the
learner's side at any point — the test looks for it (docs/lab-spec.md §13).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from norboten.labs.manifest import Lab
from norboten.paths import repo_root
from norboten.session import guest
from norboten.session.engine import Engine, EngineError
from norboten.session.state import Session
from norboten.tui import data

LAB = "linux-92-rated-end-to-end"
CHECK = "01_motd_world_readable"

COLLECT = """import os


def collect(ctx):
    path = "/srv/example/motd"
    if not os.path.exists(path):
        return {"exists": False}
    return {"exists": True, "mode": os.stat(path).st_mode & 0o7777}
"""

JUDGE = """import stat


def judge(facts, ctx):
    if not facts["exists"]:
        return ctx.failed("CRITERION: the file is gone")
    if not facts["mode"] & stat.S_IROTH:
        return ctx.failed("CRITERION: others cannot read it")
    return ctx.passed("CRITERION: readable")
"""


def _rated_lab(root: Path) -> Path:
    lab = root / "linux" / LAB
    shutil.copytree(repo_root() / "labs" / "_template", lab)
    text = (lab / "lab.yaml").read_text().replace("linux-00-template", LAB)
    text = text.replace(
        "base_images: [ubuntu-26.04, alpine]", "base_images: [ubuntu-26.04-container]"
    )
    text = text.replace("runtime: vm", "runtime: container")
    text = text.replace("reboot_required: true", "reboot_required: false")
    (lab / "lab.yaml").write_text(text + "rated: true\n")
    (lab / "collect").mkdir()
    (lab / "collect" / f"{CHECK}.py").write_text(COLLECT)
    (lab / "check" / f"{CHECK}.py").write_text(JUDGE)
    return lab


@pytest.fixture
def server(tmp_path, monkeypatch):
    from norboten_api import deps
    from norboten_api.main import create_app
    from norboten_api.settings import settings

    rated_root = tmp_path / "server-rated"
    _rated_lab(rated_root)
    monkeypatch.setenv("NORBOTEN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NORBOTEN_RATED_DIR", str(rated_root))
    monkeypatch.setenv("NORBOTEN_DATABASE_URL", "memory://")
    monkeypatch.setenv("NORBOTEN_DEBUG_USER", "e2e-learner")
    settings.cache_clear()
    deps.rated_catalogue.cache_clear()
    with TestClient(create_app()) as client:
        assert (
            client.post(
                "/me",
                json={"nick": "e2e", "country": "PL"},
                headers={"X-Debug-User": "e2e-learner"},
            ).status_code
            == 201
        )
        data.use(client)
        # the learner's machine has no rated directory of its own
        monkeypatch.setenv("NORBOTEN_RATED_DIR", str(tmp_path / "nothing-here"))
        yield client
        data.use(None)
    settings.cache_clear()
    deps.rated_catalogue.cache_clear()


def _secrets_on_disk(home: Path) -> list[Path]:
    return [
        p for p in home.rglob("*") if p.is_file() and "CRITERION" in p.read_text(errors="ignore")
    ]


@pytest.mark.docker
def test_a_rated_attempt_is_issued_collected_and_judged_on_the_server(server, tmp_path) -> None:
    from norboten import rated

    labs = rated.refresh()
    assert [lab.id for lab in labs] == [LAB]
    lab = Lab.load(rated.home() / LAB)
    assert sorted(p.name for p in lab.path.iterdir()) == ["briefing.md", "lab.yaml"]

    engine = Engine(lab)
    try:
        with pytest.raises(EngineError, match="unrated"):
            Engine(Lab.load(repo_root() / "labs" / "hello")).start(rated=True)

        session, resumed = engine.start()
        assert not resumed and session.rated and session.rated_attempt["attempt_id"]
        # the faults are in, from memory: the machine is broken and nothing was left behind
        assert engine.inst.run("stat -c %a /srv/example/motd", sudo=True).out.strip() == "600"
        assert engine.inst.run(f"test -e {guest.GUEST_DIR}", sudo=True).code != 0
        for refused in (engine.hint, engine.solution, engine.reset, engine.live):
            with pytest.raises(EngineError):
                refused()

        failed = engine.check()
        assert failed.graded and not failed.passed
        assert failed.passes[0].results[0].message == "not yet (judged on the server)"
        after = Session.load(LAB)
        assert after.rated_outcome == "failed" and "key" not in after.rated_attempt
        assert after.rated_attempt["rating_delta"]["linux-basics"] < 0
        with pytest.raises(EngineError, match="over"):
            engine.check()

        # R again: the same machine, restored, a new attempt; this time the learner fixes it
        session, resumed = engine.start()
        assert not resumed and session.rated_outcome == ""
        engine.inst.run("chmod 0644 /srv/example/motd", sudo=True)
        passed = engine.check()
        assert passed.passed and passed.score_percent == 100
        won = Session.load(LAB)
        assert (
            won.rated_outcome == "passed" and won.rated_attempt["rating_delta"]["linux-basics"] > 0
        )

        profile = server.get("/me", headers={"X-Debug-User": "e2e-learner"}).json()
        assert [h["rated"] for h in profile["history"]] == [True, True]
        assert _secrets_on_disk(tmp_path / "home") == []
        assert "CRITERION" not in (Session.path_for(LAB).with_suffix(".last.json")).read_text()
    finally:
        engine.destroy()


@pytest.fixture
def quiz_server(tmp_path, monkeypatch):
    from norboten_api import deps
    from norboten_api.main import create_app
    from norboten_api.settings import settings

    folder = tmp_path / "server-rated" / "quizzes"
    folder.mkdir(parents=True)
    shutil.copy(repo_root() / "quizzes" / "bash.yaml", folder / "bash.yaml")
    monkeypatch.setenv("NORBOTEN_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("NORBOTEN_RATED_DIR", str(tmp_path / "server-rated"))
    monkeypatch.setenv("NORBOTEN_DATABASE_URL", "memory://")
    monkeypatch.setenv("NORBOTEN_DEBUG_USER", "e2e-quiz")
    settings.cache_clear()
    deps.rated_banks.cache_clear()
    with TestClient(create_app()) as client:
        head = {"X-Debug-User": "e2e-quiz"}
        assert client.post(
            "/me", json={"nick": "e2equiz", "country": "PL"}, headers=head
        ).is_success
        data.use(client)
        yield client
        data.use(None)
    settings.cache_clear()
    deps.rated_banks.cache_clear()


async def test_a_rated_theory_run_through_the_quiz_screen(quiz_server) -> None:
    from textual.app import App

    from norboten import rated
    from norboten.quiz.bank import load
    from norboten.quiz.remote import RemoteQuiz
    from norboten.tui.quiz import QuizScreen

    key = {q.id: q.answer for q in load(repo_root() / "quizzes" / "bash.yaml").bank.questions}
    assert [b["topic"] for b in rated.refresh_banks()] == ["bash"]
    quiz = RemoteQuiz.start("bash")
    assert quiz.current.explanation.startswith("The answer, and why")  # nothing known yet

    class Host(App):
        def on_mount(self) -> None:
            self.push_screen(QuizScreen("Bash", "bash", [], quiz=quiz))

    app = Host()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        screen = app.screen
        for _ in range(quiz.total):
            q = quiz.current
            for choice in key[q.id]:
                await pilot.press(str("abcdef".index(choice) + 1))
            await pilot.press("enter")
            await pilot.pause()
            assert quiz.history[-1].correct, q.id
            assert "Right" in str(screen.query_one("#feedback").render())
            await pilot.press("n")
            await pilot.pause()
        assert quiz.finished and quiz.result["outcome"] == "passed"
        assert all(d > 0 for d in quiz.result["rating_delta"].values())

    history = quiz_server.get("/me", headers={"X-Debug-User": "e2e-quiz"}).json()["history"]
    assert history[0]["kind"] == "quiz" and history[0]["rated"] is True
