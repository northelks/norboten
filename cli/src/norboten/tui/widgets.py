"""The pieces the screens are built from: the player, the heatmap, topic bars, the side panels."""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta

import pyte
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Static

from norboten.tui import data
from norboten.tui.theme import (
    AMBER,
    BG,
    BRAND,
    DIM,
    GREEN,
    LEVELS,
    RED,
    STATUS_MARK,
    TEXT,
    duration,
    flag,
)

# ---------------------------------------------------------------------------------------------
# The top line
# ---------------------------------------------------------------------------------------------


class TopBar(Static):
    """`[ norboten ]` at the right-hand end of the top line, and nothing else: what a screen is
    about is on the screen itself. On the main screen the sections share its line, on the left."""

    DEFAULT_CSS = """
    TopBar { height: 1; width: 1fr; background: #0f1512; color: #4ade80; text-style: bold;
             content-align: right middle; padding: 0 1; }
    """

    def __init__(self) -> None:
        super().__init__(Text(BRAND))


class SectionTabs(Horizontal):
    """The sections along the top, `1 Home  2 Labs …`, keyed the way the footer draws keys; the
    current one is lit. A click switches to it, as its number does."""

    DEFAULT_CSS = """
    SectionTabs { height: 1; width: 1fr; background: #0f1512; padding: 0 1; }
    SectionTabs > .tab { width: auto; color: #8a948e; margin-right: 2; }
    SectionTabs > .tab:hover { color: #e8ece9; }
    SectionTabs > .tab.-current { color: #ffffff; background: #173524; text-style: bold; }
    """

    class Chosen(Message):
        def __init__(self, sid: str) -> None:
            super().__init__()
            self.sid = sid

    def __init__(self, sections: list[tuple[str, str]], **kw) -> None:
        super().__init__(**kw)
        self.sections = sections

    def compose(self) -> ComposeResult:
        for n, (sid, title) in enumerate(self.sections, start=1):
            label = Text.assemble((f" {n} ", f"bold {BG} on {GREEN}"), f" {title} ")
            yield _Tab(label, sid, id=f"tab-{sid}", classes="tab")

    def light(self, sid: str) -> None:
        for tab in self.query(_Tab):
            tab.set_class(tab.sid == sid, "-current")


class _Tab(Static):
    def __init__(self, label: Text, sid: str, **kw) -> None:
        super().__init__(label, **kw)
        self.sid = sid

    def on_click(self) -> None:
        self.post_message(SectionTabs.Chosen(self.sid))


# ---------------------------------------------------------------------------------------------
# Terminal player
# ---------------------------------------------------------------------------------------------

#: pyte names the eight ANSI colours the way xterm's resources do; Rich wants its own names.
_ANSI = {
    "black": "#1b2320",
    "red": "#f87171",
    "green": "#4ade80",
    "brown": "#fbbf24",
    "yellow": "#fbbf24",
    "blue": "#60a5fa",
    "magenta": "#c084fc",
    "cyan": "#22d3ee",
    "white": "#e8ece9",
    "brightblack": "#5c6660",
    "brightred": "#fca5a5",
    "brightgreen": "#86efac",
    "brightbrown": "#fde68a",
    "brightyellow": "#fde68a",
    "brightblue": "#93c5fd",
    "brightmagenta": "#d8b4fe",
    "brightcyan": "#67e8f9",
    "brightwhite": "#ffffff",
}

#: A recording plays at real speed, except that nobody wants to watch someone think: a pause
#: longer than this is cut down to it.
MAX_IDLE = 1.2
#: How many commands a prev/next press skips.
SKIP = 3


def _colour(name: str, default: str) -> str:
    if name == "default":
        return default
    if name in _ANSI:
        return _ANSI[name]
    if len(name) == 6 and all(c in "0123456789abcdefABCDEF" for c in name):
        return f"#{name}"
    return default


def render_screen(screen: pyte.Screen, cursor: bool = True) -> Text:
    """A pyte screen as Rich text, colours and all."""
    out = Text(no_wrap=True, overflow="crop")
    for y in range(screen.lines):
        if y:
            out.append("\n")
        row = screen.buffer[y]
        for x in range(screen.columns):
            ch = row[x]
            fg = _colour(ch.fg, TEXT)
            bg = _colour(ch.bg, BG)
            if ch.reverse:
                fg, bg = bg, fg
            if cursor and y == screen.cursor.y and x == screen.cursor.x:
                fg, bg = BG, GREEN
            style = f"{'bold ' if ch.bold else ''}{fg} on {bg}"
            out.append(ch.data or " ", style=style)
    return out


class TermPlayer(Vertical, can_focus=True):
    """Replays a recording through a real terminal emulator.

    Controls sit above the screen, the way a video player's do: back three commands, play or pause,
    stop, forward three commands. Skipping pauses playback — you skipped to look at something.
    """

    BINDINGS = [
        Binding("space", "toggle", "Play/pause"),
        Binding("left,[", "prev", f"-{SKIP} cmds"),
        Binding("right,]", "next", f"+{SKIP} cmds"),
        Binding("backspace,0", "stop", "Stop"),
    ]

    playing: reactive[bool] = reactive(False)

    class Moved(Message):
        def __init__(self, player: TermPlayer, command: int) -> None:
            super().__init__()
            self.player = player
            self.command = command

    def __init__(self, cast: data.Cast | None = None, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.cast = cast
        self.t = 0.0
        self.i = 0
        self.screen_: pyte.Screen | None = None
        self.stream: pyte.Stream | None = None
        self._last_tick = time.monotonic()

    def compose(self) -> ComposeResult:
        with Horizontal(classes="player-bar"):
            yield Button(f"⏮ {SKIP} cmds", id="p-prev", compact=True)
            yield Button("▶ Play", id="p-play", compact=True)
            yield Button("■ Stop", id="p-stop", compact=True)
            yield Button(f"{SKIP} cmds ⏭", id="p-next", compact=True)
            yield Static("", id="p-status", classes="player-status")
        yield Static("", id="p-screen", classes="player-screen")

    def on_mount(self) -> None:
        self.set_interval(1 / 24, self._tick)
        self.load(self.cast)

    # -- loading and seeking -------------------------------------------------------------------

    def load(self, cast: data.Cast | None) -> None:
        self.cast = cast
        self.playing = False
        self._rewind()
        self._paint()

    def _rewind(self) -> None:
        width, height = (self.cast.width, self.cast.height) if self.cast else (80, 12)
        self.screen_ = pyte.Screen(width, height)
        self.stream = pyte.Stream(self.screen_)
        self.t = 0.0
        self.i = 0

    def _feed_until(self, t: float) -> bool:
        events = self.cast.events if self.cast else []
        fed = False
        while self.i < len(events) and events[self.i][0] <= t:
            _, kind, payload = events[self.i]
            if kind == "o":
                self.stream.feed(payload)
                fed = True
            self.i += 1
        self.t = t
        return fed

    def seek(self, t: float) -> None:
        if t < self.t:
            self._rewind()
        self._feed_until(max(0.0, t))
        self._paint()

    @property
    def command_index(self) -> int:
        """The last command typed at or before the playhead; -1 before the first."""
        commands = self.cast.commands if self.cast else []
        idx = -1
        for n, c in enumerate(commands):
            if c["at"] <= self.t + 1e-6:
                idx = n
        return idx

    def _jump(self, delta: int) -> None:
        if not self.cast or not self.cast.commands:
            return
        self.playing = False
        target = min(max(self.command_index + delta, 0), len(self.cast.commands) - 1)
        # land just after the command was entered, so its line is on screen
        self.seek(self.cast.commands[target]["at"] + 0.05)
        self.post_message(self.Moved(self, target))

    # -- playback ------------------------------------------------------------------------------

    def _tick(self) -> None:
        now = time.monotonic()
        dt, self._last_tick = now - self._last_tick, now
        if not self.playing or not self.cast:
            return
        events = self.cast.events
        if self.i >= len(events):
            self.playing = False
            self._paint()
            return
        target = self.t + dt
        gap = events[self.i][0] - target
        if gap > MAX_IDLE:
            target = events[self.i][0] - MAX_IDLE
        before = self.command_index
        if self._feed_until(target):
            self._paint()
        else:
            self._status()
        after = self.command_index
        if after != before:
            self.post_message(self.Moved(self, after))

    def watch_playing(self, playing: bool) -> None:
        try:
            self.query_one("#p-play", Button).label = "⏸ Pause" if playing else "▶ Play"
        except Exception:
            return
        self._status()

    def _status(self) -> None:
        try:
            status = self.query_one("#p-status", Static)
        except Exception:
            return
        if not self.cast:
            status.update(Text("nothing loaded", style=DIM))
            return
        n = len(self.cast.commands)
        idx = self.command_index + 1
        state = (
            "playing"
            if self.playing
            else ("ended" if self.i >= len(self.cast.events) else "paused")
        )
        status.update(
            Text.assemble(
                (f" {state} ", GREEN if self.playing else DIM),
                f" {duration(self.t)} / {duration(self.cast.duration)}",
                (f"  ·  command {idx}/{n}", DIM),
            )
        )

    def _paint(self) -> None:
        try:
            target = self.query_one("#p-screen", Static)
        except Exception:
            return
        if self.screen_ is None:
            return
        target.update(render_screen(self.screen_, cursor=bool(self.cast)))
        self._status()

    # -- controls ------------------------------------------------------------------------------

    def action_toggle(self) -> None:
        if not self.cast:
            return
        if self.i >= len(self.cast.events):  # at the end: play again from the top
            self._rewind()
        self._last_tick = time.monotonic()
        self.playing = not self.playing

    def action_stop(self) -> None:
        self.playing = False
        self._rewind()
        self._paint()

    def action_prev(self) -> None:
        self._jump(-SKIP)

    def action_next(self) -> None:
        self._jump(SKIP)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        {
            "p-prev": self.action_prev,
            "p-play": self.action_toggle,
            "p-stop": self.action_stop,
            "p-next": self.action_next,
        }[event.button.id or "p-play"]()


# ---------------------------------------------------------------------------------------------
# A year of work
# ---------------------------------------------------------------------------------------------


def _level(n: int, best: int) -> int:
    if n <= 0:
        return 0
    if best <= 1:
        return 4
    return min(4, 1 + (3 * (n - 1)) // max(best - 1, 1))


class Heatmap(Widget, can_focus=True):
    """One cell per day for a year, like the web profile's. Arrows move a cursor over the days,
    and the line underneath says what was done on the one under it — the TUI's hover."""

    BINDINGS = [
        Binding("left", "move(-7)", "Week back", show=False),
        Binding("right", "move(7)", "Week on", show=False),
        Binding("up", "move(-1)", "Day back", show=False),
        Binding("down", "move(1)", "Day on", show=False),
    ]

    DEFAULT_CSS = "Heatmap { height: 11; text-wrap: nowrap; text-overflow: ellipsis; }"

    cursor: reactive[date | None] = reactive(None)

    def __init__(self, contributions: dict, history: list[dict], *, id: str | None = None):
        super().__init__(id=id)
        self.update_data(contributions, history)

    def update_data(self, contributions: dict, history: list[dict]) -> None:
        self.days = {date.fromisoformat(k): v for k, v in contributions.get("days", {}).items()}
        self.end = date.fromisoformat(contributions.get("end") or date.today().isoformat())
        self.start = self.end - timedelta(days=364)
        self.best = int(contributions.get("best_day") or max(self.days.values(), default=0))
        self.total = int(contributions.get("total") or sum(self.days.values()))
        self.streak = int(contributions.get("streak") or 0)
        self.by_day: dict[date, list[dict]] = {}
        for a in history:
            day = datetime.fromtimestamp(a["started_at"]).date()
            self.by_day.setdefault(day, []).append(a)
        latest = max(self.days, default=self.end)
        self.cursor = latest
        self.refresh()

    def action_move(self, delta: int) -> None:
        cur = self.cursor or self.end
        self.cursor = min(max(cur + timedelta(days=delta), self.start), self.end)

    def watch_cursor(self) -> None:
        self.refresh()

    def render(self) -> Text:
        first = self.start - timedelta(days=self.start.weekday())  # a Monday
        weeks = ((self.end - first).days // 7) + 1
        # Two columns a week and four for the day names: a narrow terminal shows the latest weeks.
        room = max((self.size.width - 4) // 2, 4) if self.size.width else weeks
        if room < weeks:
            first += timedelta(days=7 * (weeks - room))
            weeks = room
        out = Text(no_wrap=True, overflow="crop")
        # month labels
        months = [" "] * (weeks * 2)
        for w in range(weeks):
            d = first + timedelta(days=7 * w)
            if d.day <= 7:
                label = d.strftime("%b")
                for k, ch in enumerate(label):
                    if 2 * w + k < len(months):
                        months[2 * w + k] = ch
        out.append("    " + "".join(months) + "\n", style=DIM)
        for row in range(7):
            out.append(("Mon ", "    ", "Wed ", "    ", "Fri ", "    ", "Sun ")[row], style=DIM)
            for w in range(weeks):
                d = first + timedelta(days=7 * w + row)
                if d < self.start or d > self.end or d < first:
                    out.append("  ")
                    continue
                n = self.days.get(d, 0)
                colour = LEVELS[_level(n, self.best)]
                if d == self.cursor and self.has_focus:
                    out.append("▣", style=f"bold {GREEN}")
                else:
                    out.append("■", style=colour)
                out.append(" ")
            out.append("\n")
        out.append("    less ", style=DIM)
        for c in LEVELS:
            out.append("■ ", style=c)
        out.append("more", style=DIM)
        out.append(
            f"     {self.total} attempts in a year · best day {self.best} · streak {self.streak}\n",
            style=DIM,
        )
        out.append_text(self._detail())
        return out

    def _detail(self) -> Text:
        d = self.cursor
        if d is None:
            return Text("")
        n = self.days.get(d, 0)
        head = Text.assemble((f"    {d:%a %d %b %Y}", GREEN), f" · {n} attempt{'s' * (n != 1)}")
        done = self.by_day.get(d, [])
        if done:
            labs = ", ".join(f"{a['lab_id']} {'✓' if a['passed'] else '✗'}" for a in done[:6]) + (
                " …" if len(done) > 6 else ""
            )
            head.append(f"  ·  {labs}", style=TEXT)
        elif n:
            head.append("  ·  older than the attempts listed below", style=DIM)
        if not self.has_focus:
            head.append("   Tab, then arrows", style=DIM)
        return head

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()


# ---------------------------------------------------------------------------------------------
# By topic
# ---------------------------------------------------------------------------------------------

RATING_FLOOR, RATING_CEIL = 800, 2200


def topic_bars(radar: list[dict], width: int = 28) -> Text:
    """The radar as bars, grouped the way the web profile groups its spokes. Amber is provisional.

    `width` is the bar alone; a row is 42 columns more than that."""
    out = Text(no_wrap=True, overflow="ellipsis")
    group = None
    for spoke in radar:
        if spoke["group"] != group:
            group = spoke["group"]
            out.append(f"{'' if not out.plain else chr(10)}{group.upper()}\n", style=f"bold {DIM}")
        rating = spoke.get("rating")
        out.append(f"  {spoke['title'][:22]:<22} ", style=TEXT if rating else DIM)
        if rating is None:
            out.append("·" * width, style="#26302b")
            out.append("  not played\n", style=DIM)
            continue
        frac = (rating - RATING_FLOOR) / (RATING_CEIL - RATING_FLOOR)
        filled = max(1, min(width, round(frac * width)))
        provisional = (spoke.get("rd") or 0) > 125
        out.append("█" * filled, style=AMBER if provisional else GREEN)
        out.append("░" * (width - filled), style="#1b2320")
        out.append(f" {round(rating):>5}", style="bold")
        out.append(f" ±{round(spoke.get('rd') or 0):<3}", style=DIM)
        out.append(f" {spoke['games']:>3}g\n", style=DIM)
    return out


def strongest(radar: list[dict], n: int = 5) -> Text:
    played = sorted((s for s in radar if s.get("rating")), key=lambda s: -s["rating"])[:n]
    if not played:
        return Text("Nothing rated yet.", style=DIM)
    out = Text()
    for i, s in enumerate(played, 1):
        out.append(f"{i}. ", style=DIM)
        out.append(f"{s['title']:<24}", style=TEXT)
        out.append(f"{round(s['rating'])}\n", style=f"bold {GREEN}")
    return out


def profile_header(profile: dict) -> Text:
    user, overall = profile["user"], profile["overall"]
    out = Text()
    out.append(f"{user['nick']}", style=f"bold {GREEN}")
    out.append(f"  {flag(user['country'])} {user['country']}", style=TEXT)
    if user.get("github_login"):
        link = f"https://github.com/{user['github_login']}"
        out.append("  github.com/", style=DIM)
        out.append(user["github_login"], style=f"{TEXT} link {link}")
    if user.get("seed"):
        out.append("  sample account", style=f"{BG} on {AMBER}")
    out.append("\n")
    out.append(f"{overall['rating']}", style="bold")
    out.append(f" ± {overall['rd']}", style=DIM)
    if overall.get("provisional"):
        out.append("  provisional", style=AMBER)
    out.append(
        f"   ·   {profile['passed']} passed of {profile['attempts']} attempts",
        style=DIM,
    )
    since = datetime.fromtimestamp(user.get("created_at") or time.time())
    out.append(f"   ·   since {since:%b %Y}", style=DIM)
    return out


# ---------------------------------------------------------------------------------------------
# Side panels
# ---------------------------------------------------------------------------------------------


class DoctorPanel(Static):
    """`doctor`, run the moment the TUI opens. The verdict stays in view while you work."""

    findings: list = []

    def on_mount(self) -> None:
        self.border_title = "doctor"
        self.update(Text("checking this machine…", style=DIM))
        self.run_doctor()

    @work(thread=True, exclusive=True, group="doctor")
    def run_doctor(self) -> None:
        from norboten import doctor

        try:
            findings = doctor.run()
        except Exception as e:  # doctor must never take the TUI down with it
            self.app.call_from_thread(self.update, Text(f"doctor failed: {e}", style=RED))
            return
        self.app.call_from_thread(self._show, findings)

    def on_resize(self) -> None:
        if self.findings:
            self._draw(self.findings)

    def _show(self, findings: list) -> None:
        self._draw(findings)
        done = getattr(self.app, "doctor_done", None)
        if done is not None:
            done(findings)

    def _draw(self, findings: list) -> None:
        from norboten import doctor

        self.findings = findings
        out = Text()
        room = max(self.size.width - 17, 8)  # the mark and the name take 17 columns
        for f in findings:
            mark, colour = STATUS_MARK[f.status]
            detail = f.detail if len(f.detail) <= room else f.detail[: room - 1] + "…"
            out.append(f"{mark} ", style=f"bold {colour}")
            out.append(f"{f.name[:14]:<15}", style=TEXT)
            out.append(f"{detail}\n", style=DIM)
        ready = doctor.ready(findings)
        out.append("\n")
        out.append(
            " READY " if ready else " NOT READY ", style=f"bold {BG} on {GREEN if ready else RED}"
        )
        warn = sum(1 for f in findings if f.status == "warn")
        if warn:
            out.append(f"  {warn} warning{'s' * (warn != 1)}", style=AMBER)
        out.append("   d re-run · 8 details", style=DIM)
        self.update(out)
        self.border_subtitle = "ready" if ready else "not ready"


class AccountPanel(Static):
    """Who is signed in, and the rating that follows — or how to sign in."""

    def on_mount(self) -> None:
        self.border_title = "account"
        self.refresh_account()

    @work(thread=True, exclusive=True, group="account")
    def refresh_account(self) -> None:
        from norboten.tutor.client import ApiUnavailable

        if not data.signed_in():
            self.app.call_from_thread(
                self.update,
                Text.assemble(
                    ("not signed in\n\n", DIM),
                    "Labs, theory and journals work without an account. Sign in to be rated "
                    "and to appear on the boards.\n\n",
                    ("a", f"bold {BG} on {GREEN}"),
                    (" sign in", DIM),
                ),
            )
            return
        try:
            profile = data.me()
        except ApiUnavailable as e:
            self.app.call_from_thread(
                self.update, Text.assemble(("signed in · offline\n", AMBER), (str(e), DIM))
            )
            return
        if profile is None:
            self.app.call_from_thread(
                self.update,
                Text.assemble(
                    ("signed in, no nick yet\n\n", AMBER),
                    ("7", f"bold {BG} on {GREEN}"),
                    (" choose one on the You screen", DIM),
                ),
            )
            return
        user, overall = profile["user"], profile["overall"]
        text = Text.assemble(
            (user["nick"], f"bold {GREEN}"),
            f"  {flag(user['country'])}\n",
            (f"{overall['rating']}", "bold"),
            (f" ± {overall['rd']}", DIM),
            ("  provisional" if overall["provisional"] else "", AMBER),
            "\n",
            (f"{profile['passed']} passed · {profile['attempts']} attempts\n", DIM),
            (f"streak {profile['contributions'].get('streak', 0)} days", DIM),
        )
        self.app.call_from_thread(self.update, text)


class SessionsPanel(Static):
    """Lab VMs this machine knows about, and where each one stands."""

    def on_mount(self) -> None:
        self.border_title = "sessions"
        self.refresh_sessions()
        self.set_interval(5, self.refresh_sessions)

    def refresh_sessions(self) -> None:
        from norboten.labs.store import all_labs
        from norboten.session.state import all_sessions

        sessions = all_sessions()
        if not sessions:
            self.update(Text("no lab started yet\n2 opens the catalogue", style=DIM))
            return
        short = {lab.id: lab.manifest.short_id for lab in all_labs()}
        out = Text(no_wrap=True, overflow="ellipsis")
        for s in sorted(sessions, key=lambda s: -s.updated_at)[:8]:
            colour = GREEN if s.state.value == "passed" else AMBER if s.rated else TEXT
            out.append(f"{short.get(s.lab_id, s.lab_id)[:12]:<12}", style=colour)
            out.append(f" {s.state.value:<11}", style=DIM)
            if s.clock_started_at and not s.finished:
                out.append(f"⏱ {duration(time.time() - s.clock_started_at)}", style=GREEN)
            elif s.rated:
                out.append("rated", style=DIM)
            out.append("\n")
        self.update(out)
