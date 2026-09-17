"""Dialogs: confirm, ask, sign in, help, and one attempt in detail."""

from __future__ import annotations

import time
from datetime import datetime

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static

from norboten.tui.theme import AMBER, BG, DIM, GREEN, RED, TEXT, duration


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [Binding("escape,n", "dismiss(False)", "No"), Binding("y", "dismiss(True)", "Yes")]

    def __init__(self, question: str, detail: str = "", danger: bool = True) -> None:
        super().__init__()
        self.question, self.detail, self.danger = question, detail, danger

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(Text(self.question, style=f"bold {RED if self.danger else GREEN}"))
            if self.detail:
                yield Static(Text(self.detail, style=DIM), classes="dialog-detail")
            with Horizontal(classes="dialog-buttons"):
                yield Button("y  Yes", id="yes", variant="error" if self.danger else "success")
                yield Button("n  No", id="no")

    @on(Button.Pressed)
    def _answer(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class AskScreen(ModalScreen[str | None]):
    """One line of text: a question for the tutor, a nick, anything."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, title: str, placeholder: str = "", detail: str = "") -> None:
        super().__init__()
        self.title_text, self.placeholder, self.detail = title, placeholder, detail

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static(Text(self.title_text, style=f"bold {GREEN}"))
            if self.detail:
                yield Static(Text(self.detail, style=DIM), classes="dialog-detail")
            yield Input(placeholder=self.placeholder, id="ask-input")
            yield Static(Text("Enter to send · Esc to cancel", style=DIM))

    @on(Input.Submitted)
    def _send(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())


class DraftScreen(ModalScreen[dict | None]):
    """How many questions to draft on a bank's subject, and what about; it says who will write."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, title: str, models: tuple[str, list[str]] | None) -> None:
        super().__init__()
        self.title_text, self.models = title, models

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog wide"):
            yield Static(Text(f"Draft questions: {self.title_text}", style=f"bold {GREEN}"))
            if self.models is None:
                yield Static(
                    Text(
                        "Nothing here can draft questions. Install Claude Code and sign in "
                        "(`claude`), or make three models reachable — a writer and two that answer "
                        "blind — from ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY or the "
                        "models a local Ollama has pulled. Then open norboten again.",
                        style=RED,
                    ),
                    classes="dialog-detail",
                )
                yield Static(Text("Esc to close", style=DIM))
                return
            writer, solvers = self.models
            yield Static(
                Text.assemble(
                    ("writes         ", DIM),
                    writer,
                    "\n",
                    ("answers blind  ", DIM),
                    ", ".join(solvers),
                    "\n\n",
                    (
                        "Each question is four or more model calls on your subscription or keys. "
                        "What passes the blind solve and the critic becomes your own practice "
                        "bank; it is never rated and never leaves this machine.",
                        DIM,
                    ),
                ),
                classes="dialog-detail",
            )
            yield Static(Text("how many (1–10)", style=DIM))
            yield Input(value="3", placeholder="how many", id="draft-count", type="integer")
            yield Static(Text("about (optional)", style=DIM))
            yield Input(
                placeholder="about (optional): e.g. systemd timers after a reboot", id="draft-about"
            )
            yield Static(Text("Enter to start · Esc to cancel", style=DIM))

    @on(Input.Submitted)
    def _go(self, event: Input.Submitted) -> None:
        raw = self.query_one("#draft-count", Input).value.strip()
        count = max(1, min(int(raw) if raw.isdigit() else 3, 10))
        about = self.query_one("#draft-about", Input).value.strip()
        self.dismiss({"count": count, "about": about or None})


class ModelScreen(ModalScreen[str | None]):
    """Pick the model the tutor and the review use, from what this machine has."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, choices: list, current: str) -> None:
        super().__init__()
        self.choices, self.current = choices, current

    def compose(self) -> ComposeResult:
        from textual.widgets import OptionList
        from textual.widgets.option_list import Option

        options = [
            Option(
                Text.assemble("auto", ("  Claude Code, then a key, then Ollama", DIM)), id="auto"
            )
        ]
        options += [
            Option(Text.assemble(c.model, (f"  {c.source}", DIM)), id=c.model) for c in self.choices
        ]
        with Vertical(classes="dialog wide"):
            yield Static(Text("Tutor model", style=f"bold {GREEN}"))
            yield Static(
                Text(
                    f"now: {self.current}. "
                    + (
                        "Nothing else is available here."
                        if not self.choices
                        else "Enter picks one; the tutor and the review use it from now on."
                    ),
                    style=DIM,
                ),
                classes="dialog-detail",
            )
            yield OptionList(*options, id="model-list")
            yield Static(Text("Enter to choose · Esc to cancel", style=DIM))

    def on_option_list_option_selected(self, event) -> None:
        self.dismiss(event.option.id)


class PickScreen(ModalScreen[str | None]):
    """Choose one of a few things by name: Enter picks, Esc leaves."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, title: str, items: list[tuple[str, str]]) -> None:
        super().__init__()
        self.title_text, self.items = title, items

    def compose(self) -> ComposeResult:
        from textual.widgets import OptionList
        from textual.widgets.option_list import Option

        with Vertical(classes="dialog wide"):
            yield Static(Text(self.title_text, style=f"bold {GREEN}"))
            yield OptionList(*(Option(label, id=key) for key, label in self.items), id="pick-list")
            yield Static(Text("Enter to open · Esc to cancel", style=DIM))

    def on_option_list_option_selected(self, event) -> None:
        self.dismiss(event.option.id)


class SignInScreen(ModalScreen[bool]):
    """Signing in without leaving the TUI: with GitHub, through its device flow.

    The dialog shows the code GitHub issued, large, and the page to type it on — any browser on any
    device will do, so a headless machine signs in the same way. It opens a browser itself when
    this machine has one to open. Meanwhile it polls, at the interval GitHub asks for, until GitHub
    says yes, no, or the code expires. `c` copies the code; Esc gives up.
    """

    BINDINGS = [
        Binding("escape", "dismiss(False)", "Give up"),
        Binding("c", "copy", "Copy the code"),
        Binding("o", "open", "Open the page"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.started = None
        self.done = False
        self.remember = True

    def compose(self) -> ComposeResult:
        from textual.widgets import Checkbox

        with Vertical(classes="dialog wide", id="signin"):
            yield Static(Text("Sign in with GitHub", style=f"bold {GREEN}"))
            yield Static(
                Text(
                    "No password and no email: GitHub tells Norboten who you are, once. Your "
                    "GitHub token never reaches this machine, and Norboten keeps none.",
                    style=DIM,
                ),
                classes="dialog-detail",
            )
            yield Static("", id="signin-where", classes="dialog-detail")
            yield Static("", id="signin-code")
            yield Checkbox("Remember this machine for 90 days", value=True, id="signin-remember")
            yield Static(
                Text(
                    "Remembered, the token is kept in ~/.norboten/credentials.json, readable "
                    "only by you. Not remembered, it lives twelve hours and only until you quit "
                    "norboten.",
                    style=DIM,
                ),
                classes="dialog-detail",
            )
            yield Static("", id="signin-status")
            with Horizontal(classes="dialog-buttons"):
                yield Button("c  Copy the code", id="copy")
                yield Button("o  Open the page", id="open")
                yield Button("Esc  Give up", id="close")

    def on_mount(self) -> None:
        self._say("asking the server to start a sign-in…")
        self.begin(self.remember)

    def on_unmount(self) -> None:
        self.done = True  # the polling thread stops at its next wake

    def on_checkbox_changed(self, event) -> None:
        self.remember = event.value  # read by the polling thread when the sign-in finishes

    def _say(self, text: str, style: str = DIM) -> None:
        self.query_one("#signin-status", Static).update(Text(text, style=style))

    def _show(self, started) -> None:
        self.started = started
        self.query_one("#signin-where", Static).update(
            Text.assemble(
                ("Open ", DIM),
                (started.verification_uri, f"bold {GREEN}"),
                (" in a browser — here or on your phone — and type this code:", DIM),
            )
        )
        self.query_one("#signin-code", Static).update(
            Text(f"  {started.user_code}  ", style=f"bold {BG} on {GREEN}")
        )
        self._say("waiting for GitHub…")
        if _can_open_browser():
            self.action_open()

    def action_copy(self) -> None:
        if self.started is None:
            return
        self.app.copy_to_clipboard(self.started.user_code)
        self._say(f"copied {self.started.user_code} — waiting for GitHub…")

    def action_open(self) -> None:
        if self.started is None:
            return
        import webbrowser

        try:
            webbrowser.open(self.started.verification_uri)
        except webbrowser.Error:
            return

    @on(Button.Pressed, "#copy")
    def _copy(self) -> None:
        self.action_copy()

    @on(Button.Pressed, "#open")
    def _open(self) -> None:
        self.action_open()

    @on(Button.Pressed, "#close")
    def _close(self) -> None:
        self.dismiss(False)

    # -- the server ------------------------------------------------------------------------------

    @work(thread=True, exclusive=True)
    def begin(self, remember: bool) -> None:
        from norboten import auth
        from norboten.tutor.client import ApiUnavailable

        try:
            started = auth.start(remember)
        except (auth.LoginError, ApiUnavailable) as e:
            self.app.call_from_thread(self._say, f"✗ {e}", RED)
            return
        self.app.call_from_thread(self._show, started)
        interval = started.interval
        deadline = time.monotonic() + started.expires_in
        while not self.done and time.monotonic() < deadline:
            slept = 0.0
            while slept < interval and not self.done:
                time.sleep(0.1)
                slept += 0.1
            if self.done:
                return
            try:
                answer = auth.poll(started.poll_id, self.remember)
            except auth.LoginError as e:
                self.app.call_from_thread(self._say, f"✗ {e} — Esc, then a to try again", RED)
                return
            except ApiUnavailable as e:
                self.app.call_from_thread(self._say, f"✗ {e}", RED)
                return
            if isinstance(answer, auth.Waiting):
                interval = answer.interval
                continue
            self.done = True
            self.app.call_from_thread(self._say, "✓ signed in", f"bold {GREEN}")
            self.app.call_from_thread(self.dismiss, True)
            return
        if not self.done:
            self.app.call_from_thread(
                self._say, "✗ the code expired — Esc, then a to try again", RED
            )


def _can_open_browser() -> bool:
    """A browser this process could open: not over SSH, and a desktop to open it on."""
    import os
    import sys

    if os.environ.get("SSH_CONNECTION") or os.environ.get("NORBOTEN_NO_BROWSER"):
        return False
    return sys.platform == "darwin" or bool(
        os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    )


class AttemptScreen(ModalScreen[None]):
    """One attempt from a profile, in full."""

    BINDINGS = [Binding("escape,enter", "dismiss", "Close")]

    def __init__(self, attempt: dict) -> None:
        super().__init__()
        self.attempt = attempt

    def compose(self) -> ComposeResult:
        a = self.attempt
        when = datetime.fromtimestamp(a["started_at"])
        verdict = ("PASSED", GREEN) if a["passed"] else ("NOT YET", RED)
        body = Text.assemble(
            (a["lab_id"], f"bold {GREEN}"),
            (f"   {a.get('kind', 'lab')}\n\n", DIM),
            (f" {verdict[0]} ", f"bold {BG} on {verdict[1]}"),
            f"   score {a['score_percent']}%",
            (
                f"   {'rated' if a.get('rated') else 'unrated'}\n\n",
                AMBER if a.get("rated") else DIM,
            ),
            ("started   ", DIM),
            f"{when:%a %d %b %Y, %H:%M}\n",
            ("took      ", DIM),
            f"{duration(a['duration_seconds'])}\n",
        )
        deltas = a.get("rating_delta") or {}
        if deltas:
            body.append("\nrating moved\n", style=DIM)
            for topic, d in sorted(deltas.items(), key=lambda kv: -abs(kv[1])):
                body.append(f"  {topic:<24}", style=TEXT)
                body.append(f"{d:+.0f}\n", style=GREEN if d >= 0 else RED)
        elif not a.get("rated"):
            body.append("\nan unrated attempt is recorded and never moves the rating\n", style=DIM)
        with Vertical(classes="dialog wide"):
            yield Static(body)
            yield Static(Text("Esc to close", style=DIM))


HELP = """\
[b #4ade80]Everywhere[/]
  1–8          Home · Labs · Theory · Journals · Play · Ratings · You · System
  ← →          the section to the left or right
  a            sign in (or out)          d   re-run doctor
  ?            this help                 q   quit
  Ctrl+P       commands: sections, doctor, sign-in, setup, quit

[b #4ade80]Labs[/]  (on the catalogue)
  ↑ ↓          move · the briefing follows the cursor
  Enter        open the lab               f   next track filter
  u            pull a published lab from the registry

[b #4ade80]A lab[/]
  s            start (boots, breaks)      i   choose the base image
  o            shell on the VM (exit returns here)
  w            watch the checks live      x   quick check, no reboot
  c            check + reboot = a grade   h   next hint for the selected check
  t            ask the tutor              r   reset (faults re-applied)
  l            read what the hint points at, in its journal
  C            coach: a note when a live check changes (with w)
  m            review the finished attempt (after a pass or S)
  k            serial console             b   bootloader console
  p            shell, recorded (Play)     P   recorded and streamed live
  j            the lab's journal          y   theory questions
  S            surrender                  v   reference solution
  z            stop the VM                D   destroy the VM
  Esc          back

[b #4ade80]A rated lab[/]  (+ in the Rated column; needs a sign-in and the server)
  s            start: the server issues an attempt and the clock runs
  c            collect the facts, reboot, collect again — the server judges
  S            give the attempt up (rated as a loss)
               no hints, live checks, tutor, reset or solution: they would answer it

[b #4ade80]Theory[/]
  g            draft more questions on the bank's subject (your Claude Code or keys)
  r            timed / untimed            1–6 toggle an answer · Enter answer · n next
               a rated bank is always timed, and graded on the server

[b #4ade80]Play[/]
  Space        play / pause               ← [   back 3 commands
  0 Backspace  stop                       → ]   forward 3 commands

[b #4ade80]Journals[/]
  Enter        read                       e   export PDF

[b #4ade80]System[/]
  p            pull the selected image    x   remove it
  s            the setup screen           u   update norboten
  X            uninstall norboten
  m            the model the tutor and the review use

[b #4ade80]Setup[/]
  i            run the fix it shows       p   download Lima and the first image
  a            sign in                    Enter start the first lab · Esc later
"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,question_mark,q", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="dialog wide tall"):
            yield Static(Text("Keys", style=f"bold {GREEN}"))
            yield Static(HELP, markup=True)
