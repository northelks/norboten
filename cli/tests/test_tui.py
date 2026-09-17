"""TUI acceptance: the screens, the keys, and every question in the repo's banks through the real
widgets. No VM and no network: doctor is replaced, and the API is an httpx MockTransport."""

import json
import time
from datetime import date, datetime, timedelta

import httpx
import pytest
from textual.app import App
from textual.widgets import (
    ContentSwitcher,
    DataTable,
    RadioButton,
    RadioSet,
    SelectionList,
    Static,
)

from norboten import attempts, doctor, selfmanage, settings
from norboten.models import GradeReport
from norboten.quiz import bank
from norboten.quiz.session import QuizSession
from norboten.session.state import Session
from norboten.tui import data
from norboten.tui.app import MainScreen, NorbotenApp
from norboten.tui.modals import AskScreen, ConfirmScreen
from norboten.tui.quiz import QuizScreen
from norboten.tui.sections import SECTIONS, ProfileView
from norboten.tui.widgets import DoctorPanel, Heatmap, TermPlayer

ALL = [q for b in bank.all_banks() for q in b.bank.questions]

FINDINGS = [
    doctor.Finding("platform", doctor.OK, "macos on aarch64"),
    doctor.Finding("qemu", doctor.FAIL, "not found", "brew install qemu"),
]


def _offline(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("no network in tests", request=request)


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("NORBOTEN_HOME", str(tmp_path))
    monkeypatch.delenv("NORBOTEN_DEBUG_USER", raising=False)
    monkeypatch.setattr(doctor, "run", lambda: FINDINGS)
    settings.save(setup_done=True)  # the setup screen has tests of its own
    monkeypatch.setattr(selfmanage, "latest_version", lambda: None)  # no PyPI in tests
    data.use(httpx.Client(base_url="http://api.test", transport=httpx.MockTransport(_offline)))
    yield
    data.use(None)


def _profile(nick: str = "tux") -> dict:
    today = date.today()
    started = datetime.combine(today, datetime.min.time()).timestamp() + 3600
    return {
        "user": {
            "nick": nick,
            "country": "PL",
            "avatar_seed": 1,
            "created_at": 0,
            "seed": False,
            "github_login": f"{nick}-gh",
        },
        "overall": {"rating": 1612, "rd": 88, "provisional": False, "conservative": 1436},
        "radar": [
            {
                "topic": "storage-lvm",
                "title": "Storage and LVM",
                "group": "system",
                "rating": 1700.0,
                "rd": 80.0,
                "games": 12,
            },
            {
                "topic": "networking",
                "title": "Networking",
                "group": "network",
                "rating": None,
                "rd": None,
                "games": 0,
            },
        ],
        "contributions": {
            "start": (today - timedelta(days=364)).isoformat(),
            "end": today.isoformat(),
            "days": {today.isoformat(): 2},
            "total": 2,
            "best_day": 2,
            "streak": 1,
        },
        "history": [
            {
                "lab_id": "rhcsa-03-storage-and-lvm",
                "kind": "lab",
                "started_at": started,
                "duration_seconds": 900,
                "passed": True,
                "score_percent": 100,
                "rated": True,
                "rating_delta": {"storage-lvm": 14.0},
            },
            {
                "lab_id": "linux-01-disk-full",
                "kind": "lab",
                "started_at": started + 60,
                "duration_seconds": 400,
                "passed": False,
                "score_percent": 50,
                "rated": False,
                "rating_delta": {},
            },
        ],
        "attempts": 2,
        "passed": 1,
    }


def _api(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/me":
        return httpx.Response(200, json=_profile("me"))
    if request.url.path.startswith("/profile/"):
        return httpx.Response(200, json=_profile(request.url.path.rsplit("/", 1)[1]))
    if request.url.path == "/leaderboard":
        rows = [
            {
                "rank": i,
                "nick": f"p{i}",
                "country": "DE",
                "avatar_seed": i,
                "created_at": 0,
                "seed": True,
                "rating": 1800 - i,
                "rd": 60,
                "provisional": False,
                "conservative": 1680 - i,
            }
            for i in range(1, 6)
        ]
        return httpx.Response(200, json=rows)
    if request.url.path == "/play/live":
        return httpx.Response(200, json={"live": [], "recent": []})
    return httpx.Response(404)


async def _settle(pilot, seconds: float = 0.3) -> None:
    await pilot.pause()
    await pilot.pause(seconds)


# -- the main screen -----------------------------------------------------------------------------


async def test_number_keys_switch_sections():
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await _settle(pilot)
        assert isinstance(app.screen, MainScreen)
        switcher = app.screen.query_one(ContentSwitcher)
        for n, (sid, _, _) in enumerate(SECTIONS, start=1):
            await pilot.press(str(n))
            await _settle(pilot, 0.1)
            assert switcher.current == sid
        # the You section's form stays hidden when signed out, so digits still navigate
        await pilot.press("7", "2")
        await _settle(pilot, 0.1)
        assert switcher.current == "labs"
        tabs = app.screen.query_one("#tabs")
        assert [t.id for t in tabs.query(".-current")] == ["tab-labs"]
        # the arrows walk the sections, even with the cursor in the labs table, and wrap
        await pilot.press("right")
        await _settle(pilot, 0.1)
        assert switcher.current == "theory"
        await pilot.press("left", "left", "left")
        await _settle(pilot, 0.1)
        assert switcher.current == "system"
        await pilot.click("#tab-play")
        await _settle(pilot, 0.1)
        assert switcher.current == "play"
        assert not app.screen.query("#nav")  # no left menu


async def test_the_command_palette_offers_no_themes():
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await _settle(pilot)
        titles = [c.title for c in app.get_system_commands(app.screen)]
        assert "Quit" in titles and "Keys" in titles and "2 Labs" in titles
        assert not any("theme" in t.lower() for t in titles)
        assert app.available_themes.keys() >= {"norboten"}
        assert app.theme == "norboten"


async def test_labs_section_lists_every_lab_and_opens_one():
    from norboten.labs import store as lab_store
    from norboten.tui.lab import LabScreen

    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await pilot.press("2")
        await _settle(pilot)
        table = app.screen.query_one("#labs-table", DataTable)
        assert table.row_count == len(lab_store.all_labs()) >= 10
        await pilot.press("f")  # the first track filter narrows the list
        await _settle(pilot, 0.1)
        assert 0 < table.row_count < len(lab_store.all_labs())
        await pilot.press("u")  # pulling a published lab asks which one
        await _settle(pilot, 0.1)
        assert isinstance(app.screen, AskScreen)
        await pilot.press("escape")
        await _settle(pilot, 0.1)
        await pilot.press("enter")
        await _settle(pilot)
        assert isinstance(app.screen, LabScreen)
        await pilot.press("escape")
        await _settle(pilot, 0.1)
        assert isinstance(app.screen, MainScreen)


async def test_doctor_runs_on_start_and_reaches_the_system_section():
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await _settle(pilot, 0.5)
        panel = app.screen.query_one(DoctorPanel)
        assert app.findings == FINDINGS
        assert "NOT READY" in str(panel.render())
        await pilot.press("8")
        await _settle(pilot)
        full = str(app.screen.query_one("#doctor-full").render())
        assert "brew install qemu" in full


async def test_boards_say_offline_instead_of_hanging():
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await pilot.press("6")
        await _settle(pilot, 0.5)
        assert "offline" in str(app.screen.query_one("#board-head").render())


async def test_ratings_board_and_a_profile_from_it(monkeypatch):
    from norboten.tui.sections import ProfileScreen

    data.use(httpx.Client(base_url="http://api.test", transport=httpx.MockTransport(_api)))
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await pilot.press("6")
        await _settle(pilot, 0.5)
        board = app.screen.query_one("#board", DataTable)
        assert board.row_count == 5
        board.focus()
        await pilot.press("enter")
        await _settle(pilot, 0.5)
        assert isinstance(app.screen, ProfileScreen)
        head = str(app.screen.query_one(".profile-head").render())
        assert "p1" in head and "1612" in head and "github.com/p1-gh" in head


async def test_you_shows_the_profile_when_signed_in(monkeypatch):
    monkeypatch.setenv("NORBOTEN_DEBUG_USER", "me")
    data.use(httpx.Client(base_url="http://api.test", transport=httpx.MockTransport(_api)))
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await pilot.press("7")
        await _settle(pilot, 0.5)
        view = app.screen.query_one("#you-profile", ProfileView)
        assert view.display
        assert view.query_one(".attempts", DataTable).row_count == 2
        assert "Storage and LVM" in str(view.query_one(".bars").render())


async def test_you_drafts_the_nick_and_country_and_later_changes_only_the_country(monkeypatch):
    from textual.widgets import Input

    monkeypatch.setenv("NORBOTEN_DEBUG_USER", "me")
    sent, profile = [], {"made": False}

    def api(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/auth/me":
            return httpx.Response(200, json={"github_login": "Tux.Penguin", "github_id": 1})
        if path == "/geo/country":
            return httpx.Response(200, json={"country": "PL"})
        if path == "/me" and request.method == "POST":
            sent.append(json.loads(request.content))
            profile["made"] = True
            return httpx.Response(201, json={})
        if path == "/me":
            return (
                httpx.Response(200, json=_profile("tux-penguin"))
                if profile["made"]
                else (httpx.Response(404))
            )
        return _api(request)

    data.use(httpx.Client(base_url="http://api.test", transport=httpx.MockTransport(api)))
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await pilot.press("7")
        await _settle(pilot, 0.6)
        screen = app.screen
        assert screen.query_one("#nick", Input).value == "tux-penguin"
        assert screen.query_one("#country", Input).value == "PL"
        screen.query_one("#claim").press()
        await _settle(pilot, 0.6)
        assert sent == [{"nick": "tux-penguin", "country": "PL"}]
        assert screen.query_one("#you-country").display
        box = screen.query_one("#country-change", Input)
        box.value = "de"
        screen.query_one("#move").press()
        await _settle(pilot, 0.6)
        assert sent[-1] == {"country": "DE"}  # no nick: it is chosen once


async def test_a_graded_report_fills_both_reboot_columns():
    from norboten.labs import store as lab_store
    from norboten.tui.lab import LabScreen

    def phase(name: str, second_ok: bool) -> dict:
        return {
            "phase": name,
            "results": [
                {"id": "01_message_readable", "passed": True, "message": "ok"},
                {"id": "02_reply_written", "passed": second_ok, "message": "no reply.txt"},
                {"id": "99_from_an_older_version", "passed": False, "message": "gone"},
            ],
        }

    report = GradeReport.model_validate(
        {
            "lab_id": "hello",
            "lab_version": "1.0.0",
            "base_image": "alpine",
            "score_percent": 50,
            "passed": False,
            "passes": [phase("pre_reboot", True), phase("post_reboot", False)],
        }
    )
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        screen = LabScreen(lab_store.find("hello"))
        app.push_screen(screen)
        await _settle(pilot)
        screen._show_report(report)
        table = screen.query_one("#checktable", DataTable)
        assert str(table.get_cell("02_reply_written", "Pre-reboot")) == "pass"
        assert str(table.get_cell("02_reply_written", "Post-reboot")) == "fail"
        assert table.get_cell("02_reply_written", "What was observed") == "no reply.txt"
        assert "NOT YET" in str(screen.query_one("#verdict").render())


# -- widgets ---------------------------------------------------------------------------------------


def _cast() -> data.Cast:
    # the first command comes late enough that playback cannot reach it during the test
    events = [[5 + 0.1 * i, "o", f"$ cmd{i}\r\n"] for i in range(10)]
    commands = [{"at": 5 + 0.1 * i, "text": f"cmd{i}"} for i in range(10)]
    return data.Cast("t", "shipped", "hello", 40, 10, 6.0, events, commands)


class _PlayerApp(App):
    def compose(self):
        yield TermPlayer(_cast())


async def test_player_skips_three_commands_and_pauses():
    app = _PlayerApp()
    async with app.run_test(size=(80, 20)) as pilot:
        player = app.query_one(TermPlayer)
        player.focus()
        await pilot.press("space")
        assert player.playing
        await pilot.press("right")
        assert not player.playing
        assert player.command_index == 2
        await pilot.press("right")
        assert player.command_index == 5
        await pilot.press("left")
        assert player.command_index == 2 and not player.playing
        await pilot.press("0")
        assert player.t == 0 and player.command_index == -1


class _HeatApp(App):
    def compose(self):
        p = _profile()
        yield Heatmap(p["contributions"], p["history"])


async def test_heatmap_cursor_names_the_labs_of_that_day():
    app = _HeatApp()
    async with app.run_test(size=(140, 14)) as pilot:
        heat = app.query_one(Heatmap)
        heat.focus()
        await pilot.pause()
        assert heat.cursor == date.today()
        text = str(heat.render())
        assert "rhcsa-03-storage-and-lvm ✓" in text and "linux-01-disk-full ✗" in text
        await pilot.press("left")
        assert heat.cursor == date.today() - timedelta(days=7)
        assert "0 attempts" in str(heat.render())


# -- reporting -------------------------------------------------------------------------------------


def test_attempt_payload_never_names_its_own_opponent():
    s = Session("rhcsa-03", "1.0.0", "rocky-10", "nb-rhcsa-03", clock_started_at=time.time() - 120)
    report = GradeReport.model_validate(
        {
            "lab_id": "rhcsa-03",
            "lab_version": "1.0.0",
            "base_image": "rocky-10",
            "passed": True,
            "score_percent": 100,
            "passes": [],
        }
    )
    body = attempts.payload(s, report)
    assert 119 <= body["duration_seconds"] <= 125
    # nor whether it counts: only a rated lab, graded on the server, moves a rating
    assert not {"difficulty", "topics", "time_limit_minutes", "rated"} & body.keys()
    assert attempts.report(s, report) is None  # nobody signed in: nothing sent, nothing said


# -- the command line ------------------------------------------------------------------------------


def test_no_arguments_opens_the_tui(monkeypatch):
    from typer.testing import CliRunner

    from norboten import cli
    from norboten.tui import app as tui_app

    opened = []
    monkeypatch.setattr(tui_app, "run", lambda: opened.append(True))
    result = CliRunner().invoke(cli.app, [])
    assert result.exit_code == 0 and opened == [True]


@pytest.mark.parametrize(
    "gone", ["lab", "doctor", "journal", "play", "login", "logout", "whoami", "tui"]
)
def test_learner_commands_live_in_the_tui_now(gone):
    from typer.testing import CliRunner

    from norboten import cli

    result = CliRunner().invoke(cli.app, [gone, "--help"])
    assert result.exit_code != 0


def test_author_commands_stay_but_hide():
    from typer.testing import CliRunner

    from norboten import cli

    runner = CliRunner()
    assert "dev" not in runner.invoke(cli.app, ["--help"]).output
    assert runner.invoke(cli.app, ["dev", "--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["image", "--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["--version"]).output.startswith("norboten ")


# -- theory --------------------------------------------------------------------------------------


def test_quiz_session_scoring():
    qs = [q for q in ALL if q.type == "multiple"][:2]
    s = QuizSession.start("t", qs, shuffle=False)
    s.answer(set(qs[0].answer))
    s.next()
    wrong = {qs[1].choices[0].id} ^ set(qs[1].answer) or {"a"}
    s.answer(wrong)
    assert (s.correct, s.answered, s.best_streak, s.streak) == (1, 2, 1, 0)


def _pick(q, right: bool) -> set[str]:
    """A right answer, or a wrong one of the kind a learner would give."""
    if q.type == "single":
        return {q.answer[0]} if right else {next(c.id for c in q.choices if c.id not in q.answer)}
    if right:
        return set(q.answer)
    return {c.id for c in q.choices} - set(q.answer) or set(q.answer[1:])


@pytest.mark.parametrize("q", ALL, ids=[q.id for q in ALL])
def test_every_question_grades_right_and_wrong(q):
    for right in (True, False):
        s = QuizSession.start("t", [q])
        shown = s.current  # the same question, its choices in the run's own order
        assert {c.text for c in shown.choices} == {c.text for c in q.choices}
        assert {shown.choice_text(a) for a in shown.answer} == {q.choice_text(a) for a in q.answer}
        assert s.answer(_pick(shown, right)).correct is right


def test_a_run_moves_the_right_answer_around():
    firsts = {QuizSession.start("t", ALL, seed=seed).current.answer[0] for seed in range(12)}
    positions = [q.answer[0] for q in QuizSession.start("t", ALL, seed=1).questions]
    assert len(firsts) > 1 and max(positions.count(x) for x in set(positions)) < len(ALL) / 2


async def _until(pilot, ok, what: str) -> None:
    """Let the app process messages until `ok()` holds. Widgets settle through messages (a
    RadioSet mounts its buttons, and learns which one is pressed, after the fact), and a
    simulated key press would wait for idle instead, which costs ~0.1 s each."""
    for _ in range(500):
        if ok():
            return
        await pilot.pause(0)
    raise AssertionError(what)


def _shows(screen: QuizScreen, q) -> bool:
    """The question's own answer widget, with every choice in it. The last question's widget
    lingers, disabled, until it is removed, and for a moment there is none."""
    found = screen.query("#answer")
    w = found.first() if found else None
    if w is None or w.disabled:
        return False
    if q.type == "single":
        assert isinstance(w, RadioSet), q.id
        return len(w.query(RadioButton)) == len(q.choices)
    assert isinstance(w, SelectionList), q.id
    return w.option_count == len(q.choices)


def _holds(screen: QuizScreen, q, chosen: set[str]) -> bool:
    w = screen.query_one("#answer")
    if isinstance(w, RadioSet):
        return w.pressed_index >= 0 and {q.choices[w.pressed_index].id} == chosen
    return set(w.selected) == chosen


async def test_every_question_renders_and_answers_in_the_tui():
    """One app and one run through the whole bank: every question is drawn, answered and graded,
    right and wrong in turn (both answers for every question are checked above, without the UI).
    The first question of each shape is answered with keys; the rest queue the actions those keys
    are bound to on the screen's message loop, as a binding does. An app per question cost ~2.5 s
    each and was most of the suite's run time."""
    app = NorbotenApp()
    async with app.run_test(size=(120, 50)) as pilot:
        screen = QuizScreen("t", "test-topic", ALL, seed=0)
        app.push_screen(screen)
        await pilot.pause()
        shapes = set()

        async def press(by_keys: bool, key: str, action, *args) -> None:
            if by_keys:
                await pilot.press(key)
            else:
                screen.call_later(action, *args)

        for n, q in enumerate(screen.quiz.questions):
            right = n % 2 == 0
            chosen = _pick(q, right)
            by_keys = (q.type, len(q.choices)) not in shapes
            shapes.add((q.type, len(q.choices)))
            await _until(pilot, lambda: _shows(screen, q), f"{q.id}: no choices on screen")  # noqa: B023
            assert screen.quiz.current is q
            for i, c in enumerate(q.choices, start=1):
                if c.id in chosen:
                    await press(by_keys, str(i), screen.action_toggle, i)
            await _until(pilot, lambda: _holds(screen, q, chosen), f"{q.id}: choice not taken")  # noqa: B023
            await press(by_keys, "enter", screen.action_submit)
            await _until(pilot, lambda: screen.quiz.awaiting_next, f"{q.id}: answer not taken")
            assert screen.quiz.history[-1].correct is right, q.id
            assert ("right" if right else "wrong") in screen.query_one("#feedback").classes, q.id
            await press(by_keys, "enter", screen.action_submit)
        await _until(pilot, lambda: screen.quiz.finished, "the run never finished")
        assert screen.quiz.answered == len(ALL)
        assert len(shapes) == 3  # single of 4, multiple of 4 and of 5


# -- handing the terminal over -----------------------------------------------------------------


def test_a_failure_while_suspended_still_gives_the_terminal_back():
    """Textual's suspend() resumes only on a clean exit from its block; handed_over makes an error
    inside resume the app first and then surface."""
    from contextlib import contextmanager

    from norboten.tui.lab import handed_over

    class LikeTextual:
        resumed = False

        @contextmanager
        def suspend(self):
            yield  # no try/finally: exactly the shape of textual.app.App.suspend
            self.resumed = True

    app = LikeTextual()
    with pytest.raises(ConnectionError, match="no API"), handed_over(app):
        raise ConnectionError("no API")
    assert app.resumed

    bare = LikeTextual()
    with pytest.raises(ConnectionError), bare.suspend():
        raise ConnectionError("no API")
    assert not bare.resumed, "the trap this guards against"


async def test_streaming_without_an_account_says_so_instead_of_trying(monkeypatch):
    from norboten import auth
    from norboten.labs import store as lab_store
    from norboten.tui.lab import LabScreen

    monkeypatch.setattr(auth, "headers", lambda: {})
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        screen = LabScreen(lab_store.find("hello"))
        app.push_screen(screen)
        await _settle(pilot)
        monkeypatch.setattr(screen, "_require", lambda: object())
        screen.action_play(stream=True)
        await _settle(pilot, 0.2)
        assert not isinstance(app.screen, ConfirmScreen)
        log = " ".join(str(line) for line in screen.query_one("#lab-log").lines)
        assert "streaming needs an account" in log


async def _wait_for(pilot, ok, what: str) -> None:
    """For work done on a thread: give it real time, not just the message queue."""
    for _ in range(300):
        if ok():
            return
        await pilot.pause(0.01)
    raise AssertionError(what)


async def test_signing_in_shows_githubs_code_and_waits_for_it(monkeypatch):
    from norboten import auth
    from norboten.tui import modals
    from norboten.tui.modals import SignInScreen

    started = auth.DeviceStart("poll-1", "WDJB-MJHT", "https://github.com/login/device", 1, 900)
    polls = []
    answers = [auth.Waiting(1)]

    def poll(poll_id, remember):
        polls.append((poll_id, remember))
        return answers.pop(0) if answers else auth.Credentials("cli-token", time.time() + 3600)

    monkeypatch.setattr(auth, "start", lambda remember: started)
    monkeypatch.setattr(auth, "poll", poll)
    monkeypatch.setattr(modals, "_can_open_browser", lambda: False)
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await _settle(pilot)
        await pilot.press("a")
        await _wait_for(pilot, lambda: isinstance(app.screen, SignInScreen), "the sign-in dialog")
        screen = app.screen
        await _wait_for(
            pilot, lambda: "WDJB-MJHT" in str(screen.query_one("#signin-code").render()), "the code"
        )
        assert "github.com/login/device" in str(screen.query_one("#signin-where").render())
        screen.query_one("#signin-remember").value = False  # changed while GitHub waits
        for _ in range(40):  # about two polling intervals
            if not isinstance(app.screen, SignInScreen):
                break
            await pilot.pause(0.1)
        assert not isinstance(app.screen, SignInScreen)
        assert polls == [("poll-1", False), ("poll-1", False)]


async def test_a_denied_sign_in_says_so_and_stops_polling(monkeypatch):
    from norboten import auth
    from norboten.tui import modals
    from norboten.tui.modals import SignInScreen

    started = auth.DeviceStart("poll-1", "WDJB-MJHT", "https://github.com/login/device", 0, 900)
    polls = []

    def poll(poll_id, remember):
        polls.append(poll_id)
        raise auth.LoginError("denied on GitHub", 403)

    monkeypatch.setattr(auth, "start", lambda remember: started)
    monkeypatch.setattr(auth, "poll", poll)
    monkeypatch.setattr(modals, "_can_open_browser", lambda: False)
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await _settle(pilot)
        await pilot.press("a")
        await _wait_for(pilot, lambda: isinstance(app.screen, SignInScreen), "the sign-in dialog")
        screen = app.screen
        await _wait_for(
            pilot,
            lambda: "denied on GitHub" in str(screen.query_one("#signin-status").render()),
            "the refusal",
        )
        await pilot.pause(0.3)
        assert polls == ["poll-1"]
        await pilot.press("escape")
        await _settle(pilot, 0.1)
        assert not isinstance(app.screen, SignInScreen)


# -- setup ---------------------------------------------------------------------------------------

NEEDS_QEMU = [
    doctor.Finding("platform", doctor.OK, "macos on aarch64"),
    doctor.Finding(
        "qemu", doctor.FAIL, "QEMU is not installed", "brew install qemu", "brew install qemu"
    ),
]


def _setup_text(app) -> str:
    found = app.screen.query("#setup-list")  # empty until the screen has composed
    return str(found.first().render()) if found else ""


def _no_downloads(monkeypatch):
    from norboten.images import store
    from norboten.lima import install

    monkeypatch.setattr(install, "is_installed", lambda: False)
    monkeypatch.setattr(store, "remote_size", lambda image_id: None)


async def test_the_first_run_opens_setup_and_esc_remembers_it(tmp_path, monkeypatch):
    from norboten.tui.setup import SetupScreen

    (tmp_path / "settings.json").unlink()
    monkeypatch.setattr(doctor, "run", lambda: NEEDS_QEMU)
    _no_downloads(monkeypatch)
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await _until(pilot, lambda: isinstance(app.screen, SetupScreen), "setup did not open")
        await _until(pilot, lambda: "brew install qemu" in _setup_text(app), "no fix shown")
        text = _setup_text(app)
        assert "NOT READY" in text and "p downloads it" in text and "a signs in" in text
        assert "downloads when the lab starts" in text  # no published image, no mirror
        await pilot.press("escape")
        await _until(pilot, lambda: isinstance(app.screen, MainScreen), "esc did not leave")
    assert settings.setup_done()

    again = NorbotenApp()
    async with again.run_test(size=(160, 48)) as pilot:
        await _settle(pilot)
        assert isinstance(again.screen, MainScreen)
        await pilot.press("8")
        await _settle(pilot)
        await pilot.press("s")
        await _until(pilot, lambda: isinstance(again.screen, SetupScreen), "s did not open setup")


async def test_setup_runs_the_fix_after_a_yes(monkeypatch):
    from contextlib import nullcontext

    from norboten.tui import setup

    ran = []
    monkeypatch.setattr(doctor, "run", lambda: NEEDS_QEMU)
    monkeypatch.setattr(setup, "handed_over", lambda app: nullcontext())
    monkeypatch.setattr(setup, "run_command", lambda command: ran.append(command) or 0)
    _no_downloads(monkeypatch)
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await _settle(pilot)
        app.action_setup()
        await _until(pilot, lambda: "brew install qemu" in _setup_text(app), "no fix shown")
        await pilot.press("i")
        await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen), "no confirmation")
        await pilot.press("y")
        await _until(pilot, lambda: ran == ["brew install qemu"], "the command did not run")


async def test_setup_downloads_lima_with_progress(monkeypatch):
    from norboten.lima import install

    got = []

    def fake_install(progress=None):
        progress(10, 20)
        progress(10, 20)
        got.append("lima")

    _no_downloads(monkeypatch)
    monkeypatch.setattr(install, "install", fake_install)
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await _settle(pilot)
        app.action_setup()
        await _settle(pilot)
        await pilot.press("p")
        await _until(pilot, lambda: got == ["lima"], "lima was not downloaded")
        await _until(
            pilot,
            lambda: "downloaded" in str(app.screen.query_one("#setup-message").render()),
            "no word that it finished",
        )


async def test_enter_starts_the_first_lab_only_when_ready(monkeypatch):
    from norboten.tui.lab import LabScreen

    started = []
    monkeypatch.setattr(LabScreen, "action_start", lambda self, rated=False: started.append(1))
    _no_downloads(monkeypatch)
    monkeypatch.setattr(doctor, "run", lambda: NEEDS_QEMU)
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await _settle(pilot)
        app.action_setup()
        await _until(pilot, lambda: "NOT READY" in _setup_text(app), "doctor did not finish")
        await pilot.press("enter")
        await _settle(pilot)
        assert "not ready" in str(app.screen.query_one("#setup-message").render())

        monkeypatch.setattr(doctor, "run", lambda: NEEDS_QEMU[:1])
        app.screen.recheck()
        await _until(
            pilot, lambda: "READY" in _setup_text(app) and "NOT" not in _setup_text(app), "no ready"
        )
        await pilot.press("enter")
        await _until(pilot, lambda: isinstance(app.screen, LabScreen), "the lab did not open")
        await _until(pilot, lambda: started == [1], "the lab did not start")


# -- update --------------------------------------------------------------------------------------


async def test_u_on_system_quits_to_update_when_a_release_is_out(monkeypatch):
    monkeypatch.setattr(selfmanage, "latest_version", lambda: "99.0.0")
    monkeypatch.setattr(selfmanage, "receipt", lambda: selfmanage.Receipt((), "3.12"))
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await _until(pilot, lambda: app.latest == "99.0.0", "the update check did not finish")
        await pilot.press("8")
        await _settle(pilot)
        assert "99.0.0 is out" in str(app.screen.query_one("#about").render())
        await pilot.press("u")
        await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen), "no confirmation")
        await pilot.press("y")
        await _settle(pilot)
    assert app.return_value == "update"


async def test_u_says_so_when_norboten_is_current(monkeypatch):
    from norboten import __version__

    monkeypatch.setattr(selfmanage, "latest_version", lambda: __version__)
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await _until(pilot, lambda: app.latest == __version__, "the update check did not finish")
        await pilot.press("8")
        await _settle(pilot)
        await pilot.press("u")
        await _settle(pilot)
        assert not isinstance(app.screen, ConfirmScreen)
        log = " ".join(str(line) for line in app.screen.query_one("#activity").lines)
        assert "is the newest" in log


async def test_x_on_system_asks_then_quits_to_uninstall(monkeypatch, tmp_path):
    monkeypatch.setattr(selfmanage, "receipt", lambda: selfmanage.Receipt((), "3.12"))
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await _settle(pilot)
        await pilot.press("8")
        await _settle(pilot)
        await pilot.press("X")
        await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen), "no confirmation")
        assert str(tmp_path) in str(app.screen.query_one(".dialog-detail").render())
        await pilot.press("y")
        await _settle(pilot)
    assert app.return_value == "uninstall"


async def test_q_asks_before_quitting_and_n_stays():
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await _settle(pilot)
        await pilot.press("q")
        await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen), "no confirmation")
        assert "Quit norboten?" in str(app.screen.query_one(Static).render())
        await pilot.press("n")
        await _until(pilot, lambda: isinstance(app.screen, MainScreen), "did not go back")
        assert app.is_running
        await pilot.press("q")
        await _until(pilot, lambda: isinstance(app.screen, ConfirmScreen), "no confirmation")
        await pilot.press("y")
        await _settle(pilot)
    assert app.return_value is None


# -- drafting your own questions -----------------------------------------------------------------


async def test_g_without_claude_or_keys_says_what_is_needed(monkeypatch):
    from norboten.questions import pipeline
    from norboten.tui.modals import DraftScreen

    monkeypatch.setattr(pipeline, "choose_models", lambda config=None: None)
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await _settle(pilot)
        await pilot.press("3")
        await _settle(pilot)
        await pilot.press("g")
        await _until(pilot, lambda: isinstance(app.screen, DraftScreen), "no draft dialog")
        assert "Nothing here can draft" in str(app.screen.query_one(".dialog-detail").render())


async def test_g_drafts_into_a_bank_of_your_own_that_is_never_rated(monkeypatch, tmp_path):
    import yaml

    from norboten.questions import own, pipeline
    from norboten.tui.modals import DraftScreen

    monkeypatch.setattr(
        pipeline, "choose_models", lambda config=None: ("claude-code/opus", ["a", "b"])
    )
    asked = {}

    def fake_draft_more(source, *, count, about, on_attempt):
        asked.update(topic=source.topic, count=count, about=about)
        question = next(iter(source.bank.questions)).model_dump(exclude_none=True)
        question["id"] = "mine-001"
        own.drafts_path(source.topic).parent.mkdir(parents=True, exist_ok=True)
        own.drafts_path(source.topic).write_text(yaml.safe_dump({"accepted": [question]}))
        own.rebuild(source.topic, source)
        return []

    monkeypatch.setattr(own, "draft_more", fake_draft_more)
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await _settle(pilot)
        await pilot.press("3")
        await _settle(pilot)
        await pilot.press("g")
        await _until(pilot, lambda: isinstance(app.screen, DraftScreen), "no draft dialog")
        app.screen.query_one("#draft-count").value = "2"
        app.screen.query_one("#draft-about").value = "timers"
        app.screen.query_one("#draft-about").focus()
        await pilot.press("enter")
        section = app.screen.query_one("#theory")
        await _until(pilot, lambda: any(b.own for b in section.banks.values()), "no bank of yours")
        assert asked["count"] == 2 and asked["about"] == "timers"

        key = next(k for k, b in section.banks.items() if b.own)
        table = section.query_one("#banks", DataTable)
        section.rated = True
        table.move_cursor(row=table.get_row_index(key))
        await _settle(pilot)
        await pilot.press("enter")
        await _until(pilot, lambda: isinstance(app.screen, QuizScreen), "the quiz did not open")
        assert app.screen.quiz.rated is False


# -- the tutor and the review, on this machine ---------------------------------------------------


def _lab_session(state: str = "working"):
    from norboten.session.state import Session, State

    return Session(
        lab_id="hello",
        lab_version="1.0.0",
        image="alpine",
        instance="nb-test",
        state=State(state),
        started_at=time.time() - 600,
        clock_started_at=time.time() - 540,
        hint_levels={"02_reply_written": 2},
    )


async def _lab_screen(pilot, app, monkeypatch, session):
    from norboten.labs import store as lab_store
    from norboten.tui.lab import LabScreen

    screen = LabScreen(lab_store.find("hello"))
    app.push_screen(screen)
    await _settle(pilot)
    monkeypatch.setattr(screen, "_require", lambda: session)
    monkeypatch.setattr(screen, "_session", lambda: session)
    monkeypatch.setattr(screen, "_facts", lambda s: {"history": ["cat message.txt"]})
    monkeypatch.setattr(screen.engine, "last_report", lambda: None)
    return screen


async def test_t_asks_the_tutor_on_this_machines_model(monkeypatch):
    from norboten.tutor import agent, models

    asked = {}

    def fake_hint(req, *, model, solution_text="", config=None):
        asked.update(req=req, model=model, solution=solution_text)
        return agent.TutorReply(message="What does ls -l say about it?", evidence_to_look_at="ls")

    monkeypatch.setattr(
        models, "choose", lambda config=None: models.Choice("claude-code/haiku", "Claude Code")
    )
    monkeypatch.setattr(agent, "hint", fake_hint)
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        screen = await _lab_screen(pilot, app, monkeypatch, _lab_session())
        await pilot.press("t")
        await _until(pilot, lambda: isinstance(app.screen, AskScreen), "no question dialog")
        app.screen.query_one("#ask-input").value = "why can I not read it?"
        await pilot.press("enter")
        box = screen.query_one("#tutortext")
        await _until(pilot, lambda: "ls -l" in str(box.render()), "no tutor reply")
        shown = str(box.render())
        assert "claude-code/haiku (Claude Code)" in shown
        assert asked["model"] == "claude-code/haiku"
        assert asked["req"].question == "why can I not read it?"
        assert asked["req"].facts == {"history": ["cat message.txt"]}
        assert "reply.txt" in asked["solution"]  # for the guard; the request has no field for it


async def test_t_without_a_model_falls_back_to_the_hint_ladder(monkeypatch):
    from norboten.tutor import models

    monkeypatch.setattr(models, "choose", lambda config=None: None)
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        screen = await _lab_screen(pilot, app, monkeypatch, _lab_session())
        monkeypatch.setattr(
            screen.engine, "hint", lambda cid, again=False: (cid, 2, "Who may read the file?")
        )
        await pilot.press("t")
        await _until(pilot, lambda: isinstance(app.screen, AskScreen), "no question dialog")
        await pilot.press("enter")
        box = screen.query_one("#tutortext")
        await _until(pilot, lambda: "Who may read" in str(box.render()), "no ladder hint")
        assert "no model on this machine" in str(box.render())


async def test_m_waits_for_the_attempt_to_end(monkeypatch):
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        screen = await _lab_screen(pilot, app, monkeypatch, _lab_session("working"))
        await pilot.press("m")
        await _settle(pilot)
        log = " ".join(str(line) for line in screen.query_one("#lab-log").lines)
        assert "the review comes after the attempt" in log


async def test_m_reviews_a_surrendered_attempt_with_the_solution(monkeypatch):
    from norboten.tutor import models, review

    seen = {}

    def fake_review(req, solution_text, *, model, config=None):
        seen.update(req=req, solution=solution_text, model=model)
        return review.PostMortem(
            what_the_machine_was_saying="ls -l showed mode 000.",
            where_the_path_went_wrong="You read the file before its mode.",
            a_faster_path="ls -l, then the owner.",
            habit_for_next_time="Read the mode first.",
        )

    monkeypatch.setattr(
        models, "choose", lambda config=None: models.Choice("ollama/qwen2.5:1.5b", "Ollama")
    )
    monkeypatch.setattr(review, "review", fake_review)
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        screen = await _lab_screen(pilot, app, monkeypatch, _lab_session("surrendered"))
        await pilot.press("m")
        box = screen.query_one("#reviewtext")
        await _until(pilot, lambda: "Read the mode first" in str(box.render()), "no review")
        assert screen.query_one("#lab-tabs").active == "review"
        assert seen["req"].surrendered and seen["req"].minutes == 9
        assert seen["req"].commands == ["[history] cat message.txt"]
        assert seen["req"].hint_levels == {"02_reply_written": 2}
        assert "reply.txt" in seen["solution"]


async def test_m_on_system_pins_the_tutor_model(monkeypatch):
    from norboten.tui.modals import ModelScreen
    from norboten.tutor import models

    monkeypatch.setattr(
        models,
        "available",
        lambda config=None: [
            models.Choice("claude-code/sonnet", "Claude Code"),
            models.Choice("ollama/qwen2.5:1.5b", "Ollama"),
        ],
    )
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await _settle(pilot)
        await pilot.press("8")
        await _settle(pilot)
        await pilot.press("m")
        await _until(pilot, lambda: isinstance(app.screen, ModelScreen), "no model dialog")
        await pilot.press("down", "down", "enter")
        await _until(pilot, lambda: not isinstance(app.screen, ModelScreen), "still open")
    assert settings.load()["tutor_model"] == "ollama/qwen2.5:1.5b"


# -- hints that point somewhere -------------------------------------------------------------------


async def test_h_shows_the_hint_with_what_to_read(monkeypatch):
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        screen = await _lab_screen(pilot, app, monkeypatch, _lab_session())
        ladder = screen.lab.hints.checks["01_message_readable"]
        monkeypatch.setattr(
            screen.engine, "hint", lambda cid=None, again=False: (cid, 3, ladder.level_3)
        )
        await pilot.press("h")
        box = screen.query_one("#hinttext")
        await _until(pilot, lambda: "read" in str(box.render()), "no reading under the hint")
        shown = str(box.render())
        assert "man 1 chmod" in shown
        assert "How the kernel picks a triad" in shown


async def test_l_opens_the_journal_at_the_heading_the_hint_names(monkeypatch):
    from norboten.tui.lab import JournalScreen
    from norboten.tui.modals import PickScreen

    session = _lab_session()
    session.hint_levels = {"01_message_readable": 3}
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        await _lab_screen(pilot, app, monkeypatch, session)
        await pilot.press("l")
        await _until(pilot, lambda: isinstance(app.screen, PickScreen), "no choice of sections")
        await pilot.press("down", "enter")
        await _until(pilot, lambda: isinstance(app.screen, JournalScreen), "no journal")
        journal = app.screen
        assert journal.journal.id == "hello"
        await _until(pilot, lambda: journal.anchor == "", "never scrolled to the heading")
        assert journal.query_one("#journal-scroll").scroll_y > 0


async def test_l_before_any_hint_offers_nothing_to_read(monkeypatch):
    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        screen = await _lab_screen(pilot, app, monkeypatch, _lab_session())
        await pilot.press("l")
        await _settle(pilot)
        log = " ".join(str(line) for line in screen.query_one("#lab-log").lines)
        assert "nothing to read for 01_message_readable yet" in log


async def test_the_coach_speaks_when_a_live_check_changes(monkeypatch):
    from norboten.models import CheckResult, PassResult, Phase

    def live(passed: bool) -> PassResult:
        return PassResult(
            phase=Phase.LIVE,
            results=[CheckResult(id="01_message_readable", passed=passed, message="mode 600")],
        )

    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        screen = await _lab_screen(pilot, app, monkeypatch, _lab_session())
        await pilot.press("C")
        await _settle(pilot)
        screen._show_live(live(False))
        screen._show_live(live(True))
        screen._show_live(live(False))
        await _settle(pilot)
        log = " ".join(str(line) for line in screen.query_one("#lab-log").lines)
        assert "coach: 01_message_readable passes now · read:" in log
        assert "coach: 01_message_readable fails again" in log


# -- rated labs ------------------------------------------------------------------------------------


def _cached_rated_lab(home) -> str:
    """A rated lab as the Labs section keeps it: the manifest and briefing the server published."""
    from norboten import rated
    from norboten.labs import store as lab_store

    hello = lab_store.find("hello")
    target = rated.home() / "linux-93-rated-in-the-tui"
    target.mkdir(parents=True)
    manifest = hello.manifest.model_dump(mode="json") | {
        "id": "linux-93-rated-in-the-tui",
        "rated": True,
        "reboot_required": True,
    }
    import yaml

    (target / "lab.yaml").write_text(yaml.safe_dump(manifest))
    (target / "briefing.md").write_text("A rated briefing.\n")
    return manifest["id"]


async def test_a_rated_lab_is_listed_and_refuses_the_help_an_unrated_one_has(tmp_path):
    from norboten import rated
    from norboten.tui.lab import LabScreen

    lab_id = _cached_rated_lab(tmp_path)
    app = NorbotenApp()
    async with app.run_test(size=(180, 48)) as pilot:
        await pilot.press("2")
        await _settle(pilot)
        table = app.screen.query_one("#labs-table", DataTable)
        assert [str(c.label) for c in table.ordered_columns[4:6]] == ["Status", "Rated"]
        assert str(table.get_row(lab_id)[5]) == "+"
        assert str(table.get_row("hello")[5]) == "−"

        lab = next(lab for lab in rated.cached_labs() if lab.id == lab_id)
        screen = LabScreen(lab)
        app.push_screen(screen)
        await _settle(pilot)
        assert "give up" in str(screen.query_one("#lab-keys").render())
        for key in ("h", "w", "v", "r", "t"):
            await pilot.press(key)
        await _settle(pilot, 0.2)
        log = " ".join(str(line) for line in screen.query_one("#lab-log").lines)
        for what in ("hints", "live checks", "reference solution", "reset", "tutor"):
            assert f"a rated attempt has no {what}" in log


async def test_R_on_an_unrated_lab_says_it_never_rates():
    from norboten.labs import store as lab_store
    from norboten.tui.lab import LabScreen

    app = NorbotenApp()
    async with app.run_test(size=(160, 48)) as pilot:
        screen = LabScreen(lab_store.find("hello"))
        app.push_screen(screen)
        await _settle(pilot)
        await pilot.press("R")
        await _settle(pilot, 0.2)
        log = " ".join(str(line) for line in screen.query_one("#lab-log").lines)
        assert "never rated" in log and screen.busy is None
