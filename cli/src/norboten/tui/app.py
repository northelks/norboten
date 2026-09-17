"""norboten — the terminal is the product. Labs, theory, journals, recordings and ratings, on keys.

     1 Home   2 Labs   3 Theory   4 Journals   5 Play   6 Ratings   7 You   8 System   [ norboten ]
    ┌ the section ────────────────────────────────────────────┐┌ account ────────┐
    │                                                         ││ doctor          │
    │                                                         ││ sessions        │
    └─────────────────────────────────────────────────────────┘└─────────────────┘
    activity
    footer: the keys that work where the cursor is

`1`–`8` or `←`/`→` move between the sections, unless the cursor is in something that uses the
arrows itself (a text field, the player, the heatmap). Ctrl+P offers what this app has — there is
one theme, so no theme switching. Doctor runs the moment the app opens, so a machine that cannot
run labs says so before anyone starts one. The first run opens the setup screen over it
(`tui/setup.py`). A lab opens full screen (`tui/lab.py`); a theory run too (`tui/quiz.py`).
"""

from __future__ import annotations

import time
from collections.abc import Iterable

from rich.text import Text
from textual import on, work
from textual.actions import SkipAction
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.theme import Theme
from textual.widgets import ContentSwitcher, Footer, Input, RichLog

from norboten.tui import data
from norboten.tui.modals import ConfirmScreen, HelpScreen, SignInScreen
from norboten.tui.sections import SECTIONS, Section
from norboten.tui.theme import AMBER, DIM, GREEN, PANEL, RED, TEXT
from norboten.tui.widgets import (
    AccountPanel,
    DoctorPanel,
    Heatmap,
    SectionTabs,
    SessionsPanel,
    TermPlayer,
    TopBar,
)

THEME = Theme(
    name="norboten",
    primary=GREEN,
    secondary="#15803d",
    accent=GREEN,
    warning=AMBER,
    error=RED,
    success=GREEN,
    foreground=TEXT,
    background="#0b0f0d",
    surface=PANEL,
    panel="#173524",
    dark=True,
)

#: Below this width the right-hand column folds away and the section gets the room.
WIDE = 130


class MainScreen(Screen):
    BINDINGS = [
        *(
            Binding(str(n), f"show('{sid}')", title, show=False)
            for n, (sid, title, _) in enumerate(SECTIONS, start=1)
        ),
        Binding("left", "step(-1)", "Previous section", show=False, priority=True),
        Binding("right", "step(1)", "Next section", show=False, priority=True),
        Binding("a", "account", "Sign in/out"),
        Binding("d", "doctor", "Doctor"),
        Binding("question_mark", "app.help", "Keys"),
        Binding("q", "app.quit", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal(id="topline"):
            yield SectionTabs([(sid, title) for sid, title, _ in SECTIONS], id="tabs")
            yield TopBar()
        with Horizontal(id="body"):
            with ContentSwitcher(initial="home", id="content"):
                for sid, _, cls in SECTIONS:
                    yield cls(id=sid)
            with Vertical(id="side"):
                yield AccountPanel(id="account", classes="panel")
                yield DoctorPanel(id="doctor", classes="panel")
                yield SessionsPanel(id="sessions", classes="panel")
        yield RichLog(id="activity", wrap=True, max_lines=500)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#activity").border_title = "activity"
        self.action_show("home")

    def on_screen_resume(self) -> None:
        # back from a lab or a quiz: what they changed shows here at once
        self.current.refresh_data()
        self.query_one(SessionsPanel).refresh_sessions()

    def on_resize(self) -> None:
        self.query_one("#side").display = self.size.width >= WIDE

    @property
    def current(self) -> Section:
        switcher = self.query_one(ContentSwitcher)
        return self.query_one(f"#{switcher.current}", Section)

    def action_show(self, sid: str) -> None:
        self.query_one(ContentSwitcher).current = sid
        self.query_one(SectionTabs).light(sid)
        section = self.current
        section.refresh_data()
        self.call_after_refresh(section.focus_first)

    def action_step(self, delta: int) -> None:
        if isinstance(self.focused, (Input, TermPlayer, Heatmap)):
            raise SkipAction()  # the arrows are theirs
        ids = [sid for sid, _, _ in SECTIONS]
        here = ids.index(self.query_one(ContentSwitcher).current)
        self.action_show(ids[(here + delta) % len(ids)])

    @on(SectionTabs.Chosen)
    def _tab(self, event: SectionTabs.Chosen) -> None:
        self.action_show(event.sid)

    def action_doctor(self) -> None:
        self.query_one(DoctorPanel).run_doctor()
        self.app.note("running doctor")

    def action_account(self) -> None:
        from norboten import auth

        if not data.signed_in():
            self.app.push_screen(SignInScreen(), lambda ok: ok and self.app.refresh_account())
            return
        if auth.current() is None:  # NORBOTEN_DEBUG_USER: nothing stored to forget
            self.app.note("signed in through NORBOTEN_DEBUG_USER; unset it to sign out")
            return

        def confirmed(yes: bool | None) -> None:
            if yes:
                auth.forget()
                self.app.note("signed out")
                self.app.refresh_account()

        self.app.push_screen(
            ConfirmScreen("Sign out?", "The tokens on this machine are deleted.", danger=False),
            confirmed,
        )


class NorbotenApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "norboten"

    findings: list | None = None

    def on_mount(self) -> None:
        self.register_theme(THEME)
        self.theme = THEME.name
        self.push_screen(MainScreen())
        from norboten import settings

        if not settings.setup_done():
            self.action_setup()
        self.check_for_update()

    latest: str | None = None

    @work(thread=True, exclusive=True, group="update-check")
    def check_for_update(self) -> None:
        from norboten import selfmanage

        latest = selfmanage.latest_version()
        self.call_from_thread(self._update_checked, latest)

    def _update_checked(self, latest: str | None) -> None:
        from norboten import selfmanage

        self.latest = latest
        if selfmanage.is_newer(latest):
            self.note(f"norboten {latest} is out — u on System (8) updates", GREEN)
        main = self._main()
        try:
            current = main.current if main is not None else None
        except NoMatches:  # still composing; System reads self.latest when it is shown
            return
        if current is not None and current.id == "system":
            current.refresh_data()

    def _main(self) -> MainScreen | None:
        for screen in self.screen_stack:
            if isinstance(screen, MainScreen):
                return screen
        return None

    def note(self, message: str, style: str = "") -> None:
        """A line in the activity log, from anywhere on the UI thread."""
        main = self._main()
        if main is None:
            return
        line = Text.assemble((time.strftime("%H:%M:%S "), DIM), (message, style or TEXT))
        main.query_one("#activity", RichLog).write(line)

    def doctor_done(self, findings: list) -> None:
        from norboten import doctor

        self.findings = findings
        main = self._main()
        if main is None:
            return
        ready = doctor.ready(findings)
        self.note(
            "doctor: ready" if ready else "doctor: NOT READY — 8 shows what to fix",
            GREEN if ready else RED,
        )
        main.query_one("#system").show_doctor(findings)
        from norboten.tui.setup import SetupScreen

        for screen in self.screen_stack:
            if isinstance(screen, SetupScreen):
                screen.show(findings)

    def refresh_account(self) -> None:
        main = self._main()
        if main is None:
            return
        main.query_one(AccountPanel).refresh_account()
        main.current.refresh_data()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        """Ctrl+P: what this app really has. Textual's own list would offer themes, and there is
        one theme."""
        yield SystemCommand("Keys", "Every key, section by section", self.action_help)
        if isinstance(screen, MainScreen):
            for n, (sid, title, _) in enumerate(SECTIONS, start=1):
                yield SystemCommand(
                    f"{n} {title}", f"Go to {title}", lambda sid=sid: screen.action_show(sid)
                )
            yield SystemCommand("Doctor", "Check this machine again", screen.action_doctor)
            yield SystemCommand("Sign in or out", "Your account", screen.action_account)
        yield SystemCommand("Setup", "The first-run checks and fixes", self.action_setup)
        yield SystemCommand("Quit", "Close norboten", self.action_quit)

    async def action_quit(self) -> None:
        """`q`, Ctrl+Q and the palette all come here: quitting asks first."""
        if isinstance(self.screen, ConfirmScreen):
            return  # already asking

        def answered(yes: bool | None) -> None:
            if yes:
                self.exit()

        self.push_screen(
            ConfirmScreen("Quit norboten?", "Lab VMs that are running keep running.", danger=False),
            answered,
        )

    def action_setup(self) -> None:
        from norboten.tui.setup import SetupScreen

        self.push_screen(SetupScreen())


def run() -> str | None:
    """Open the TUI. Returns what should happen after it closes: "update", or None."""
    return NorbotenApp().run()
