"""One lab: the briefing, the checks, hints, the tutor and the review; every VM action, on a key.

The tutor (`t`) and the review after an attempt (`m`) run here, on the model this machine has
(`tutor/models.py`): Claude Code, the learner's own key, or a local Ollama. No server is involved.

Everything that touches the VM runs in a worker thread, one at a time, and reports through the
activity log at the bottom. The screen never blocks: a reboot that takes a minute is a minute of
log lines, not a frozen terminal.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    DataTable,
    Footer,
    Markdown,
    OptionList,
    ProgressBar,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option

from norboten import attempts
from norboten.containers import Container
from norboten.images import store
from norboten.labs.manifest import Lab
from norboten.models import GradeReport, PassResult
from norboten.session.engine import Engine
from norboten.session.state import Session
from norboten.tui.modals import AskScreen, ConfirmScreen
from norboten.tui.theme import AMBER, BG, DIM, GREEN, RED, TEXT, dots, duration
from norboten.tui.widgets import TopBar

#: The checks table's columns after the check id; their labels are also their keys.
COLUMNS = ("Now", "Pre-reboot", "Post-reboot", "What was observed")


class ImageScreen(ModalScreen[str | None]):
    """Pick the base image a lab runs on."""

    BINDINGS = [Binding("escape", "dismiss(None)", "Cancel")]

    def __init__(self, lab: Lab, current: str) -> None:
        super().__init__()
        self.lab, self.current = lab, current

    def compose(self) -> ComposeResult:
        options = []
        for image_id in self.lab.manifest.base_images:
            local = store.cached(image_id)
            note = "downloaded" if local else "downloads on start"
            mark = "● " if image_id == self.current else "  "
            options.append(Option(f"{mark}{image_id:<24} {note}", id=image_id))
        with Vertical(classes="dialog"):
            yield Static(Text("Base image", style=f"bold {GREEN}"))
            yield OptionList(*options, id="image-list")
            yield Static(Text("Enter to choose · Esc to cancel", style=DIM))

    @on(OptionList.OptionSelected)
    def _pick(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)


class JournalScreen(Screen):
    """A journal, full screen, opened at a heading when a hint points there. `e` writes a PDF."""

    BINDINGS = [
        Binding("escape,q", "app.pop_screen", "Back"),
        Binding("e", "export", "Export PDF"),
    ]

    def __init__(self, journal, anchor: str = "") -> None:
        super().__init__()
        self.journal = journal
        self.anchor = anchor

    def compose(self) -> ComposeResult:
        j = self.journal
        yield TopBar()
        yield Static(
            Text.assemble(
                (j.title, f"bold {GREEN}"),
                (f"   {j.kind} · {', '.join(j.topics)} · {j.minutes} min read", DIM),
            ),
            classes="title",
        )
        with VerticalScroll(id="journal-scroll"):
            yield Markdown(j.body)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#journal-scroll").focus()

    def on_markdown_table_of_contents_updated(self, event: Markdown.TableOfContentsUpdated) -> None:
        if self.anchor:
            self.call_after_refresh(self.goto, self.anchor)

    def goto(self, anchor: str) -> bool:
        """Scroll to the heading with this anchor, named as the site names it (journal.slug)."""
        from norboten.journal import unique_slugs

        md = self.query_one(Markdown)
        headings = [(title, hid) for level, title, hid in md.table_of_contents if level <= 3]
        for (_, hid), found in zip(headings, unique_slugs([t for t, _ in headings]), strict=True):
            if found == anchor and hid:
                md.query_one(f"#{hid}").scroll_visible(top=True, animate=False)
                self.anchor = ""
                return True
        return False

    def action_export(self) -> None:
        export_pdf(self.app, self.journal)


def export_pdf(app, journal) -> None:
    """Write a journal to ~/.norboten/journals/<id>.pdf in the background, and say where."""
    from norboten.paths import norboten_home

    def run() -> None:
        from norboten.journal_pdf import PdfUnavailable, write_pdf

        target = norboten_home() / "journals" / f"{journal.id}.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            written = write_pdf(journal, target)
        except (PdfUnavailable, OSError) as e:
            app.call_from_thread(app.notify, str(e), severity="error")
            return
        size = written.stat().st_size // 1024
        app.call_from_thread(app.notify, f"✓ {written} ({size} KiB)")

    app.notify(f"exporting {journal.id} to PDF…")
    threading.Thread(target=run, daemon=True).start()


@contextmanager
def handed_over(app) -> Iterator[None]:
    """`app.suspend()` that gives the terminal back even when the code inside fails.

    Textual resumes the app only when its `with` block ends cleanly: an exception raised inside
    skips the resume and leaves the TUI suspended for good, with the terminal in cooked mode — which
    is what a stream without an account used to do. The error is caught inside the block, so
    Textual resumes, and raised again outside it for the caller to report.
    """
    failure: BaseException | None = None
    with app.suspend():
        try:
            yield
        except Exception as e:
            failure = e
    if failure is not None:
        raise failure


class LabScreen(Screen):
    BINDINGS = [
        Binding("escape", "back", "Back"),
        Binding("s", "start", "Start"),
        Binding("R", "start(True)", "Rated", show=False),
        Binding("i", "image", "Image", show=False),
        Binding("o", "shell", "Shell"),
        Binding("w", "live", "Live checks"),
        Binding("x", "quick", "Quick check", show=False),
        Binding("c", "grade", "Check+reboot"),
        Binding("h", "hint", "Hint"),
        Binding("l", "read", "Read", show=False),
        Binding("C", "coach", "Coach", show=False),
        Binding("t", "tutor", "Tutor", show=False),
        Binding("m", "review", "Review", show=False),
        Binding("r", "reset", "Reset", show=False),
        Binding("k", "console", "Console", show=False),
        Binding("b", "boot_console", "Boot console", show=False),
        Binding("p", "play(False)", "Record", show=False),
        Binding("P", "play(True)", "Stream", show=False),
        Binding("j", "journal", "Journal", show=False),
        Binding("y", "theory", "Theory", show=False),
        Binding("S", "surrender", "Surrender", show=False),
        Binding("v", "solution", "Solution", show=False),
        Binding("z", "stop", "Stop VM", show=False),
        Binding("D", "destroy", "Destroy", show=False),
        Binding("question_mark", "app.help", "Keys"),
    ]

    def __init__(self, lab: Lab) -> None:
        super().__init__()
        self.lab = lab
        self.engine = Engine(lab, say=self._say, progress=self._progress)
        self.image = (Session.load(lab.id) or _NoSession).image or lab.manifest.base_images[0]
        self.busy: str | None = None
        self.live = None
        self.coach = False
        self.now: dict[str, bool] = {}  # each check's last result, live or graded

    # -- layout --------------------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        m = self.lab.manifest
        yield TopBar()
        with Horizontal(id="lab-body"):
            with Vertical(id="lab-main"):
                yield Static(
                    Text.assemble(
                        (m.short_id, DIM),
                        ("  ", ""),
                        (m.title, f"bold {GREEN}"),
                        ("   ", ""),
                        dots(m.difficulty),
                        (f"   {m.track.value} · ~{m.estimated_minutes} min · ", DIM),
                        (", ".join(m.topics), DIM),
                    ),
                    classes="title",
                )
                with TabbedContent(initial="briefing", id="lab-tabs"):
                    with TabPane("Briefing", id="briefing"), VerticalScroll():
                        yield Markdown(self.lab.briefing)
                    with TabPane("Checks", id="checks"):
                        yield DataTable(id="checktable", cursor_type="row")
                        yield Static("", id="verdict")
                    with TabPane("Hints", id="hints"):
                        yield Static(
                            Text(
                                "A rated attempt has no hints, no tutor and no solution: the "
                                "server judges it, and they stay there."
                                if m.rated
                                else "Select a check on the Checks tab and press h. Each press "
                                "goes one level deeper; a hint never hands over the command.",
                                style=DIM,
                            ),
                            classes="subtitle",
                        )
                        yield Static("", id="hinttext", classes="hint-text")
                    with TabPane("Tutor", id="tutor"):
                        yield Static(
                            Text(
                                "t asks the tutor about the selected check, on this machine's "
                                "model. It reads the machine's evidence and never sees the "
                                "reference solution.",
                                style=DIM,
                            ),
                            classes="subtitle",
                        )
                        yield Static("", id="tutortext", classes="hint-text")
                    with TabPane("Review", id="review"), VerticalScroll():
                        yield Static(
                            Text(
                                "m reviews a finished attempt (passed or surrendered): what the "
                                "machine was saying, where the path went wrong, a faster one.",
                                style=DIM,
                            ),
                            classes="subtitle",
                        )
                        yield Static("", id="reviewtext", classes="hint-text")
                    with TabPane("Solution", id="solution"), VerticalScroll():
                        yield Static(
                            Text("Shown after you pass, or after S (surrender).", style=DIM),
                            id="solutiontext",
                        )
            with Vertical(id="lab-side"):
                yield Static("", id="lab-status", classes="panel")
                yield Static(_keys_text(m.rated), id="lab-keys", classes="panel")
        yield ProgressBar(id="download", show_eta=True)
        yield RichLog(id="lab-log", wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#lab-status").border_title = "status"
        self.query_one("#lab-keys").border_title = "keys"
        self.query_one("#download").display = False
        table = self.query_one("#checktable", DataTable)
        for label in ("Check", *COLUMNS):
            table.add_column(label, key=label)
        for c in self.lab.manifest.checks:
            dot = Text("·", style=DIM)
            table.add_row(c.id, dot, dot, dot, "", key=c.id)
        last = self.engine.last_report()
        if last is not None:
            self._show_report(last)
        self._status()
        self.set_interval(1, self._status)

    # -- plumbing ------------------------------------------------------------------------------

    def _say(self, msg: str, style: str = "") -> None:
        line = Text.assemble((time.strftime("%H:%M:%S "), DIM), (msg, style or TEXT))

        def write() -> None:
            self.query_one("#lab-log", RichLog).write(line)
            note = getattr(self.app, "note", None)
            if note:
                note(f"{self.lab.manifest.short_id}: {msg}", style)

        if threading.get_ident() == self.app._thread_id:
            write()
        else:
            self.app.call_from_thread(write)

    def _progress(self, advance: int, total: int) -> None:
        def update() -> None:
            bar = self.query_one("#download", ProgressBar)
            bar.display = True
            if total and bar.total != total:
                bar.update(total=total, progress=0)
            bar.advance(advance)
            if total and bar.progress >= total:
                bar.display = False

        self.app.call_from_thread(update)

    def _run(self, label: str, fn: Callable[[], None]) -> None:
        """One VM action at a time, in a thread; errors land in the log, never in a traceback."""
        if self.busy:
            self._say(f"busy: {self.busy} — wait for it to finish", AMBER)
            return
        self.busy = label

        def work() -> None:
            try:
                fn()
            except Exception as e:  # every engine error is something to read, not a crash
                self._say(f"{label} failed: {e}", RED)
            finally:
                self.busy = None
                self.app.call_from_thread(self._status)

        self._say(label)
        self.run_worker(work, thread=True, group="engine", exit_on_error=False)

    def _session(self) -> Session | None:
        return Session.load(self.lab.id)

    def _rated_refuses(self, what: str) -> bool:
        """A rated lab has none of the help an unrated one has (docs/lab-spec.md §13)."""
        if self.lab.manifest.rated:
            self._say(f"a rated attempt has no {what} — the server judges it", AMBER)
            return True
        return False

    def _require(self) -> Session | None:
        s = self._session()
        if s is None:
            self._say("the lab is not started yet — press s", AMBER)
        return s

    def _check_id(self) -> str | None:
        table = self.query_one("#checktable", DataTable)
        if not table.row_count:
            return None
        return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value

    # -- the status panel ----------------------------------------------------------------------

    def _status(self) -> None:
        s = self._session()
        m = self.lab.manifest
        out = Text()

        def row(label: str, value: str | Text, style: str = TEXT) -> None:
            out.append(f"{label:<9}", style=DIM)
            out.append_text(value if isinstance(value, Text) else Text(value, style=style))
            out.append("\n")

        vm = self.engine.inst.status() if s else None
        machine = "container" if m.runtime == "container" else "vm"
        row(machine, vm or "absent", GREEN if vm == "Running" else DIM)
        row("image", s.image if s else self.image)
        state = s.state.value if s else "not started"
        row(
            "state",
            state,
            GREEN if state == "passed" else AMBER if state == "surrendered" else TEXT,
        )
        if s:
            row("mode", "rated" if s.rated else "unrated", AMBER if s.rated else DIM)
            if s.rated and s.rated_outcome:
                good = s.rated_outcome == "passed"
                row("attempt", s.rated_outcome, GREEN if good else RED)
            limit = self.engine.time_limit_minutes(s)
            if s.clock_started_at and not s.finished:
                elapsed = time.time() - s.clock_started_at
                if limit:
                    left = limit * 60 - elapsed
                    colour = RED if left < 300 else GREEN
                    row("clock", f"{duration(max(left, 0))} left of {limit}m", colour)
                else:
                    row("clock", duration(elapsed), GREEN)
            best = max((a.score_percent for a in s.attempts), default=None)
            if best is not None:
                row("attempts", f"{len(s.attempts)} · best {best}%")
            if s.hint_levels:
                row("hints", ", ".join(f"{k} {v}/4" for k, v in sorted(s.hint_levels.items())))
        else:
            row("checks", str(len(m.checks)))
            row("reboot", "graded after a reboot" if m.reboot_required else "no reboot needed")
            if m.runtime == "container":
                row("runs in", "a container (Docker or Podman), not a VM")
        if self.busy:
            out.append("\n")
            out.append(" BUSY ", style=f"bold {BG} on {AMBER}")
            out.append(f" {self.busy}\n", style=AMBER)
        if s and vm == "Running":
            inst = self.engine.inst
            out.append("\nfrom another terminal\n", style=DIM)
            if isinstance(inst, Container):
                out.append(inst.connect_hint(), style=GREEN)
            else:
                out.append(f"ssh -F {inst.ssh_config} {inst.ssh_host}", style=GREEN)
        self.query_one("#lab-status", Static).update(out)

    # -- showing results -----------------------------------------------------------------------

    def _show_live(self, p: PassResult) -> None:
        table = self.query_one("#checktable", DataTable)
        for r in p.results:
            if r.id not in table.rows:
                continue
            mark = Text("pass", style=GREEN) if r.passed else Text("fail", style=RED)
            table.update_cell(r.id, "Now", mark)
            table.update_cell(r.id, "What was observed", "" if r.passed else r.message)
            before = self.now.get(r.id)
            self.now[r.id] = r.passed
            if self.coach and before is not None and before != r.passed:
                self._coach(r.id, r.passed)

    def _show_report(self, report: GradeReport) -> None:
        table = self.query_one("#checktable", DataTable)
        columns = {"pre_reboot": "Pre-reboot", "post_reboot": "Post-reboot"}
        for p in report.passes:
            column = columns.get(p.phase.value)
            for r in p.results:
                if r.id not in table.rows:  # a report from an older version of the lab
                    continue
                mark = Text("pass", style=GREEN) if r.passed else Text("fail", style=RED)
                if column:
                    table.update_cell(r.id, column, mark)
                table.update_cell(r.id, "Now", mark)
                self.now[r.id] = r.passed
                if not r.passed:
                    table.update_cell(r.id, "What was observed", r.message)
                elif p is report.passes[0]:
                    table.update_cell(r.id, "What was observed", "")
        if not report.graded:
            allgood = report.score_percent == 100
            verdict = ("ALL PASS — NOT GRADED", AMBER) if allgood else ("NOT YET", RED)
        else:
            verdict = ("PASSED", GREEN) if report.passed else ("NOT YET", RED)
        line = Text.assemble(
            (f" {verdict[0]} ", f"bold {BG} on {verdict[1]}"),
            f"  score {report.score_percent}% (pass line {self.lab.manifest.pass_percent}%)",
        )
        if not report.graded:
            line.append("   quick check without a reboot — c to be graded", style=DIM)
        elif self.lab.manifest.rated:
            line.append("   judged on the server · R starts another attempt", style=DIM)
        elif report.passed:
            line.append("   v shows the reference solution", style=DIM)
        else:
            line.append("   stuck? select a check and press h", style=DIM)
        self.query_one("#verdict", Static).update(line)

    # -- lifecycle -----------------------------------------------------------------------------

    def action_back(self) -> None:
        self._live_off()
        self.app.pop_screen()

    def action_start(self, rated: bool = False) -> None:
        if rated and not self.lab.manifest.rated:
            self._say(
                "an unrated lab is recorded and never rated — s starts it; the rating comes from "
                "the rated labs",
                AMBER,
            )
            return
        rated = self.lab.manifest.rated

        def go() -> None:
            session, resumed = self.engine.start(image_id=self.image, rated=rated)
            if resumed:
                self._say(f"resumed on {session.image} ({session.state.value}) — o for a shell")
            elif session.rated:
                limit = self.engine.time_limit_minutes(session)
                self._say(f"rated, {limit} minutes — the clock is running. o for a shell", GREEN)
            else:
                self._say(f"ready on {session.image} — o for a shell, c to be graded", GREEN)

        self._run("starting (rated)" if rated else "starting", go)

    def action_image(self) -> None:
        def chosen(image_id: str | None) -> None:
            if not image_id:
                return
            s = self._session()
            if s and s.image != image_id:
                self._say(f"{self.lab.manifest.short_id} runs on {s.image}; D destroys it first")
                return
            self.image = image_id
            self._say(f"base image: {image_id}")
            self._status()

        self.app.push_screen(ImageScreen(self.lab, self.image), chosen)

    def action_shell(self) -> None:
        if self._require() is None or self.busy:
            return
        self._live_off()
        try:
            with handed_over(self.app):
                print(f"\n{self.engine.inst.name}: exit returns to norboten\n")
                self.engine.shell()
        except Exception as e:
            self._say(f"shell failed: {e}", RED)

    def action_stop(self) -> None:
        if self._require():
            self._live_off()
            self._run("stopping the VM", lambda: (self.engine.stop(), self._say("VM stopped")))

    def action_destroy(self) -> None:
        def confirmed(yes: bool | None) -> None:
            if yes:
                self._live_off()
                self._run(
                    "destroying the VM", lambda: (self.engine.destroy(), self._say("destroyed"))
                )

        self.app.push_screen(
            ConfirmScreen(
                f"Destroy {self.engine.inst.name}?",
                "The VM and everything you changed in it are deleted. Starting again boots a "
                "fresh copy.",
            ),
            confirmed,
        )

    def action_reset(self) -> None:
        if self._rated_refuses("reset: S gives it up, R starts again"):
            return
        if self._require() is None:
            return

        def confirmed(yes: bool | None) -> None:
            if yes:
                self._live_off()
                self._run("resetting", lambda: self._say(f"reset in {self.engine.reset():.1f}s"))

        self.app.push_screen(
            ConfirmScreen("Reset the lab?", "Your changes are thrown away; the faults return."),
            confirmed,
        )

    # -- grading -------------------------------------------------------------------------------

    def _grade(self, reboot: bool) -> None:
        if self._require() is None:
            return
        self._live_off()

        def go() -> None:
            report = self.engine.check(reboot=reboot)
            self.app.call_from_thread(self._show_report, report)
            if not report.graded:
                good = report.score_percent == 100
                self._say(
                    f"{report.score_percent}% without a reboot — c to be graded",
                    AMBER if good else RED,
                )
            else:
                verdict = "PASSED" if report.passed else "not yet"
                self._say(f"{verdict} — {report.score_percent}%", GREEN if report.passed else RED)
            line = (
                _rated_line(self._session()) if report.graded and self.lab.manifest.rated else None
            )
            line = line or attempts.report(self._session(), report)
            if line:
                self._say(line)

        self.query_one(TabbedContent).active = "checks"
        self._run("checking, then rebooting" if reboot else "quick check", go)

    def action_grade(self) -> None:
        self._grade(reboot=True)

    def action_quick(self) -> None:
        if self._rated_refuses("quick check"):
            return
        self._grade(reboot=False)

    def _live_off(self) -> None:
        if self.live is not None:
            self.live.stop()
            self.live = None

    def action_live(self) -> None:
        if self._rated_refuses("live checks"):
            return
        from norboten.session.live import LiveChecks

        if self.live is not None and self.live.running:
            self._live_off()
            self._say("live checks off")
            return
        s = self._require()
        if s is None:
            return
        if self.busy or not self.engine.inst.is_running():
            self._say("the VM is not running — s starts it", AMBER)
            return
        self.live = LiveChecks(self.engine.inst, self.lab, s.learner)
        self.live.start(
            on_pass=lambda p: self.app.call_from_thread(self._show_live, p),
            on_error=lambda e: self._say(f"live checks stopped: {e}", RED),
        )
        self.query_one(TabbedContent).active = "checks"
        self._say("live checks on — every 2 seconds, w to stop")

    # -- help ----------------------------------------------------------------------------------

    def action_hint(self) -> None:
        if self._rated_refuses("hints"):
            return
        if self._require() is None:
            return
        try:
            cid, level, text = self.engine.hint(self._check_id())
        except Exception as e:
            self._say(str(e), RED)
            return
        body = Text.assemble(
            (f"{cid} · hint {level}/4\n\n", f"bold {GREEN}"), " ".join(text.split())
        )
        refs = self.lab.hints.checks[cid].refs_upto(level)
        if refs:
            body.append("\n\nread", style=f"bold {TEXT}")
            body.append("  l opens a journal section\n", style=DIM)
            body.append_text(_refs_text(refs))
        self.query_one("#hinttext", Static).update(body)
        self.query_one(TabbedContent).active = "hints"

    def _reading(self, check_id: str, s: Session | None) -> list[str]:
        """What this learner may read for a check: up to the hint level reached, or all of it
        once the check passes."""
        ladder = self.lab.hints.checks[check_id]
        if self.now.get(check_id):
            return ladder.refs_upto(4)
        level = s.hint_levels.get(check_id, 0) if s else 0
        return ladder.refs_upto(level)

    def action_read(self) -> None:
        if self._rated_refuses("reading ladder"):
            return
        from norboten.journal import parse_ref
        from norboten.tui.modals import PickScreen

        cid = self._check_id() or next(iter(self.lab.hints.checks), None)
        if cid is None:
            return
        journals = [r for r in self._reading(cid, self._session()) if r.startswith("journal:")]
        if not journals:
            self._say(
                f"nothing to read for {cid} yet — h gives a hint, and its reading with it", AMBER
            )
            return

        def open_ref(raw: str | None) -> None:
            if raw is None:
                return
            ref = parse_ref(raw)
            journal = _journal_by_id(ref.target)
            if journal is None:
                self._say(f"no journal {ref.target} here", RED)
                return
            self.app.push_screen(JournalScreen(journal, anchor=ref.anchor))

        if len(journals) == 1:
            open_ref(journals[0])
            return
        labels = [(raw, _ref_label(raw)) for raw in journals]
        self.app.push_screen(PickScreen(f"Read for {cid}", labels), open_ref)

    def action_coach(self) -> None:
        if self._rated_refuses("coach"):
            return
        self.coach = not self.coach
        if self.coach:
            live = "" if self.live else " — w turns live checks on"
            self._say(f"coach on: a note when a check changes while you work{live}", GREEN)
        else:
            self._say("coach off")

    def _coach(self, check_id: str, passed: bool) -> None:
        ladder = self.lab.hints.checks.get(check_id)
        if ladder is None:
            return
        if passed:
            refs = ladder.refs_upto(4)
            more = f" · read: {_ref_label(refs[0])} (l)" if refs else ""
            self._say(f"coach: {check_id} passes now{more}", GREEN)
            self.app.notify(f"{check_id} passes now", title="coach")
        else:
            self._say(f"coach: {check_id} fails again — {' '.join(ladder.level_1.split())}", AMBER)
            self.app.notify(f"{check_id} fails again", title="coach", severity="warning")

    def action_tutor(self) -> None:
        if self._rated_refuses("tutor"):
            return
        s = self._require()
        if s is None:
            return
        target = self._check_id()

        def asked(question: str | None) -> None:
            if question is None:
                return
            self.query_one("#tutortext", Static).update(Text("asking the tutor…", style=DIM))
            self.query_one(TabbedContent).active = "tutor"
            self._run("asking the tutor", lambda: self._ask(s, target, question))

        self.app.push_screen(
            AskScreen(
                "Ask the tutor",
                "what have you tried, and what did you see?",
                f"about {target}" if target else "",
            ),
            asked,
        )

    def _checks(self) -> list[dict]:
        from norboten.session.grading import check_outcomes

        report = self.engine.last_report()
        if report is None:
            return []
        outcome = check_outcomes(self.lab.manifest, report.passes)
        checks = []
        for c in self.lab.manifest.checks:
            last = next((r for p in report.passes for r in p.results if r.id == c.id), None)
            checks.append(
                {
                    "id": c.id,
                    "passed": outcome[c.id],
                    "message": last.message if last else "",
                    "evidence": (last.evidence if last else "")[:2000],
                }
            )
        return checks

    def _facts(self, s: Session) -> dict:
        from norboten.session import guest

        try:
            return guest.facts(self.engine.inst, self.lab, s.learner)
        except Exception:
            return {}

    def _solution_text(self, s: Session) -> str:
        try:
            return self.lab.solution_for(s.image or self.image).read_text()
        except OSError:
            return ""

    def _ask(self, s: Session, check_id: str | None, question: str) -> None:
        from norboten.questions.providers import ProviderError
        from norboten.session.grading import first_failing
        from norboten.tutor import agent, models

        m = self.lab.manifest
        target = check_id or first_failing(m, self.engine.last_report())
        level = s.hint_levels.get(target, 1)
        box = self.query_one("#tutortext", Static)

        def ladder(why: str) -> None:
            _, lvl, text = self.engine.hint(target, again=True)
            body = Text.assemble(
                (f"! {why}\n", AMBER),
                ("here is the lab's own hint instead\n\n", DIM),
                (f"{target} · hint {lvl}/4\n\n", f"bold {GREEN}"),
                " ".join(text.split()),
            )
            self.app.call_from_thread(box.update, body)

        choice = models.choose()
        if choice is None:
            ladder(models.HOW_TO_GET_ONE)
            return
        request = agent.TutorRequest(
            lab_id=self.lab.id,
            objectives=m.objectives,
            checks=self._checks(),
            hint_level=level,
            hint_text=self.lab.hints.checks[target].level(level),
            facts=self._facts(s),
            question=question,
        )
        try:
            reply = agent.hint(request, model=choice.model, solution_text=self._solution_text(s))
        except ProviderError as e:
            ladder(f"the tutor on {choice.model} failed: {e}")
            return
        body = Text.assemble(
            (f"{target} · hint level {level}/4 · {choice.label}\n\n", f"bold {GREEN}"),
            " ".join(reply.message.split()),
        )
        if reply.evidence_to_look_at:
            body.append(f"\n\nlook at: {reply.evidence_to_look_at}", style=DIM)
        self.app.call_from_thread(box.update, body)

    def action_review(self) -> None:
        if self._rated_refuses("review"):
            return
        from norboten.session.state import State

        s = self._require()
        if s is None:
            return
        if s.state not in (State.PASSED, State.SURRENDERED):
            self._say("the review comes after the attempt: pass the lab, or surrender (S)", AMBER)
            return
        self.query_one("#reviewtext", Static).update(Text("reviewing the attempt…", style=DIM))
        self.query_one(TabbedContent).active = "review"
        self._run("reviewing the attempt", lambda: self._review(s))

    def _review(self, s: Session) -> None:
        from norboten.questions.providers import ProviderError
        from norboten.session.state import State
        from norboten.tutor import commands, models, review

        box = self.query_one("#reviewtext", Static)
        choice = models.choose()
        if choice is None:
            self.app.call_from_thread(box.update, Text(models.HOW_TO_GET_ONE, style=AMBER))
            return
        started = s.clock_started_at or s.started_at
        facts = self._facts(s)
        request = review.PostMortemRequest(
            lab_id=self.lab.id,
            objectives=self.lab.manifest.objectives,
            checks=self._checks(),
            commands=commands.merged(self.lab.id, started, facts.get("history") or []),
            facts=facts,
            hint_levels=dict(s.hint_levels),
            surrendered=s.state == State.SURRENDERED,
            minutes=max(0, int((time.time() - started) // 60)),
        )
        try:
            result = review.review(request, self._solution_text(s), model=choice.model)
        except ProviderError as e:
            self.app.call_from_thread(box.update, Text(f"the review failed: {e}", style=RED))
            return
        sources = (
            "no commands were found"
            if not request.commands
            else (f"{len(request.commands)} commands, from recordings and shell history")
        )
        body = Text.assemble((f"review · {choice.label} · {sources}\n", f"bold {GREEN}"))
        for title, text in (
            ("What the machine was saying", result.what_the_machine_was_saying),
            ("Where the path went wrong", result.where_the_path_went_wrong),
            ("A faster path", result.a_faster_path),
            ("For next time", result.habit_for_next_time),
        ):
            body.append(f"\n{title}\n", style=f"bold {TEXT}")
            body.append(" ".join(text.split()) + "\n")
        self.app.call_from_thread(box.update, body)

    def _show_solution(self, text: str) -> None:
        self.query_one("#solutiontext", Static).update(Text(text))
        self.query_one(TabbedContent).active = "solution"

    def action_solution(self) -> None:
        if self._rated_refuses("reference solution"):
            return
        if self._require() is None:
            return
        try:
            self._show_solution(self.engine.solution())
        except Exception as e:
            self._say(str(e), AMBER)

    def action_surrender(self) -> None:
        if self._require() is None:
            return
        if self.lab.manifest.rated:
            self._give_up()
            return

        def confirmed(yes: bool | None) -> None:
            if yes:
                try:
                    self._show_solution(self.engine.surrender())
                except Exception as e:
                    self._say(str(e), RED)
                    return
                self._say("surrendered — the reference solution is on the Solution tab", AMBER)
                self._status()

        self.app.push_screen(
            ConfirmScreen(
                "Surrender?",
                "The reference solution is shown and this attempt stops counting. You can reset "
                "and try again later.",
            ),
            confirmed,
        )

    def _give_up(self) -> None:
        def confirmed(yes: bool | None) -> None:
            if not yes:
                return

            def go() -> None:
                answer = self.engine.abandon()
                moves = _moves(answer.get("rating_delta") or {})
                self._say(f"gave the rated attempt up — rated as a loss{moves}", AMBER)

            self._run("giving the attempt up", go)

        self.app.push_screen(
            ConfirmScreen(
                "Give this rated attempt up?",
                "It is rated as a loss, like running out of time, and no solution is shown. R "
                "starts another attempt on the same machine.",
            ),
            confirmed,
        )

    # -- the terminal, handed over -------------------------------------------------------------

    def action_console(self, boot: bool = False) -> None:
        from norboten.host import host_arch
        from norboten.lima import console, qmp

        if self._require() is None or self.busy:
            return
        inst = self.engine.inst
        if isinstance(inst, Container):
            self._say("a container has no console or bootloader — o opens a shell", AMBER)
            return
        self._live_off()
        if not inst.is_running():
            self._say("the VM is not running — s starts it", AMBER)
            return
        sock = inst.boot_console_socket if boot and host_arch().value == "aarch64" else None
        try:
            with handed_over(self.app):
                if boot:
                    qmp.hard_reset(inst.dir / "qmp.sock")
                console.attach(
                    sock or inst.serial_socket,
                    banner=f"[{inst.name} {'boot ' if boot else ''}console — Ctrl-] to detach]",
                )
        except Exception as e:
            self._say(f"console: {e}", RED)

    def action_boot_console(self) -> None:
        if self._require() is None:
            return
        if isinstance(self.engine.inst, Container):
            self.action_console(boot=True)
            return

        def confirmed(yes: bool | None) -> None:
            if yes:
                self.action_console(boot=True)

        self.app.push_screen(
            ConfirmScreen(
                "Press the reset button?",
                "The VM resets immediately — as if power was cut — and you are attached to the "
                "console it boots on, in time for the bootloader menu. Ctrl-] detaches.",
            ),
            confirmed,
        )

    def action_play(self, stream: bool = False) -> None:
        if self._require() is None or self.busy:
            return

        def go(yes: bool | None = True) -> None:
            if not yes:
                return
            self._record(stream)

        if stream:
            from norboten import auth

            if not auth.headers():
                self._say(
                    "streaming needs an account — a on the main screen signs in; p records locally",
                    AMBER,
                )
                return
            self.app.push_screen(
                ConfirmScreen(
                    "Stream this session live?",
                    "Anyone on the site can watch your terminal while it runs. Do not type "
                    "secrets you care about.",
                    danger=False,
                ),
                go,
            )
        else:
            go()

    def _record(self, stream: bool) -> None:
        from norboten.play.session import Play

        self._live_off()
        play = Play(
            inst=self.engine.inst,
            lab_id=self.lab.id,
            title=self.lab.manifest.title,
            stream=stream,
        )
        lines: list[str] = []
        path: Path | None = None
        try:
            with handed_over(self.app):
                self.engine.ensure_running()
                print("\nrecording — exit the shell to stop\n")
                recording, _ = play.run(say=lambda m: (lines.append(m), print(m)))
                path = play.save(recording)
        except Exception as e:
            self._say(f"recording failed: {e}", RED)
            return
        for line in lines:
            self._say(line)
        self._say(
            f"recorded {len(recording.commands)} commands, {recording.duration:.0f}s → {path} "
            "(5 plays it back)",
            GREEN,
        )

    # -- reading -------------------------------------------------------------------------------

    def action_journal(self) -> None:
        if self._rated_refuses("journal"):
            return
        from norboten.journal import JournalError, find

        try:
            journal = find(self.lab.id)
        except JournalError:
            self._say("this lab has no journal yet", AMBER)
            return
        self.app.push_screen(JournalScreen(journal))

    def action_theory(self) -> None:
        if self._rated_refuses("theory bank here"):
            return
        from norboten.quiz import bank
        from norboten.tui.quiz import QuizScreen

        try:
            b = bank.find_topic(self.lab.id)
        except Exception:
            self._say("this lab has no theory questions yet", AMBER)
            return
        self.app.push_screen(
            QuizScreen(b.bank.title, b.topic, b.bank.questions, topics=b.bank.topics)
        )


def _moves(deltas: dict) -> str:
    if not deltas:
        return ""
    return ": " + ", ".join(f"{topic} {delta:+.0f}" for topic, delta in sorted(deltas.items()))


def _rated_line(s: Session | None) -> str | None:
    """What the server said about a closed rated attempt, from the session it was written to."""
    if s is None or not s.rated or not s.rated_outcome:
        return None
    overall = (s.rated_attempt.get("overall") or {}).get("rating")
    tail = f" → {overall}" if overall else ""
    return f"rated {s.rated_outcome}{_moves(s.rated_attempt.get('rating_delta') or {})}{tail}"


class _NoSession:
    image = ""


def _journal_by_id(journal_id: str):
    from norboten import journal

    return next((j for j in journal.all_journals() if j.id == journal_id), None)


def _ref_label(raw: str) -> str:
    """A reference as a reader wants it: a journal's title and heading, a man page, a URL."""
    from norboten import journal

    ref = journal.parse_ref(raw)
    if ref.kind != "journal":
        return ref.label
    found = _journal_by_id(ref.target)
    heading = journal.heading_for(found, ref.anchor) if found else None
    title = found.title.split(" — ")[0] if found else ref.target
    return f"{title} › {(heading or ref.anchor).replace('`', '')}"


def _refs_text(refs: list[str]) -> Text:
    out = Text()
    for i, raw in enumerate(refs, 1):
        out.append(f"  {i}  ", style=DIM)
        out.append(_ref_label(raw) + "\n", style=TEXT if raw.startswith("journal:") else DIM)
    return out


def _keys_text(rated: bool = False) -> Text:
    if rated:
        return _key_rows(
            (
                ("s", "start rated", "?", "all keys"),
                ("o", "shell", "c", "check + reboot"),
                ("k", "console", "b", "boot console"),
                ("p", "record", "P", "stream"),
                ("S", "give up", "i", "image"),
                ("z", "stop VM", "D", "destroy"),
            ),
            "judged on the server: no hints, no live checks, no solution",
        )
    return _key_rows(
        (
            ("s", "start", "o", "shell"),
            ("i", "image", "k", "console"),
            ("w", "live checks", "x", "quick check"),
            ("c", "check + reboot", "h", "hint"),
            ("l", "read", "C", "coach"),
            ("t", "tutor", "m", "review"),
            ("r", "reset", "b", "boot console"),
            ("p", "record", "P", "stream"),
            ("j", "journal", "y", "theory"),
            ("S", "surrender", "v", "solution"),
            ("z", "stop VM", "D", "destroy"),
        ),
    )


def _key_rows(rows, note: str = "") -> Text:
    out = Text()
    for k1, l1, k2, l2 in rows:
        out.append(f" {k1} ", style=f"bold {BG} on {GREEN}")
        out.append(f" {l1:<15}", style=TEXT)
        out.append(f" {k2} ", style=f"bold {BG} on {GREEN}")
        out.append(f" {l2}\n", style=TEXT)
    if note:
        out.append(f"\n{note}\n", style=AMBER)
    out.append("\nEsc back · ? all keys", style=DIM)
    return out
