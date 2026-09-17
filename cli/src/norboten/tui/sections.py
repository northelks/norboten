"""The eight sections of the main screen: Home, Labs, Theory, Journals, Play, Ratings, You, System.

Each is a container that owns its keys; they apply while focus is inside it. Anything that needs
the network runs in a worker and says "offline" when the API cannot be reached — the labs, theory,
journals and local recordings never wait for it.
"""

from __future__ import annotations

import time
from datetime import datetime

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Input,
    Markdown,
    OptionList,
    ProgressBar,
    Static,
)
from textual.widgets.option_list import Option

from norboten import __version__, progress
from norboten.images import store
from norboten.labs import store as lab_store
from norboten.session.state import Session, State
from norboten.topics import TOPICS
from norboten.tui import data
from norboten.tui.theme import (
    AMBER,
    BG,
    DIM,
    GREEN,
    LOGO_WIDTH,
    RED,
    STATUS_MARK,
    TAGLINE,
    TEXT,
    dots,
    duration,
    flag,
    logo,
)
from norboten.tui.widgets import (
    Heatmap,
    TermPlayer,
    TopBar,
    profile_header,
    strongest,
    topic_bars,
)


def _open_lab(app, lab_id: str) -> None:
    from norboten import rated
    from norboten.tui.lab import LabScreen

    lab = next((lab for lab in rated.cached_labs() if lab.id == lab_id), None)
    app.push_screen(LabScreen(lab or lab_store.find(lab_id)))


class Section(Vertical):
    """A section: `focus_first()` puts the cursor where the section is used from."""

    label = ""

    def focus_first(self) -> None:
        for widget in self.query("DataTable, OptionList, Input, TermPlayer, Heatmap"):
            if widget.focusable and self._visible_here(widget):
                widget.focus()
                return

    def _visible_here(self, widget) -> bool:
        node = widget
        while node is not None and node is not self:
            if not node.display:
                return False
            node = node.parent
        return True

    def refresh_data(self) -> None:
        """Re-read whatever the section shows; called when it is switched to."""


# ---------------------------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------------------------


class HomeSection(Section):
    label = "Home"

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static("", id="home-logo")
            yield Static(
                Text.assemble(
                    (TAGLINE[0].upper() + TAGLINE[1:] + ".", f"bold {TEXT}"),
                    (
                        "  Real VMs with something genuinely wrong, graded by machine state — "
                        "and again after a reboot.",
                        DIM,
                    ),
                ),
                id="home-tagline",
            )
            with Horizontal(id="home-cards"):
                yield Static("", id="card-labs", classes="card")
                yield Static("", id="card-theory", classes="card")
                yield Static("", id="card-rating", classes="card")
            yield Static(Text("Pick up where you left off", style=f"bold {GREEN}"), classes="h2")
            yield OptionList(id="home-next")

    def on_resize(self) -> None:
        self._logo()

    def _logo(self) -> None:
        target = self.query_one("#home-logo", Static)
        if self.size.width >= LOGO_WIDTH + 4:
            target.update(logo())
        else:
            target.update(Text("[ norboten ]", style=f"bold {GREEN}"))

    def refresh_data(self) -> None:
        self._logo()
        labs = lab_store.all_labs()
        sessions = {s.lab_id: s for s in [Session.load(lab.id) for lab in labs] if s}
        passed = sum(1 for s in sessions.values() if s.state == State.PASSED)
        self.query_one("#card-labs", Static).update(
            Text.assemble(
                ("labs passed\n", DIM),
                (f"{passed}", f"bold {GREEN}"),
                (f" / {len(labs)}\n", DIM),
                (f"{len(sessions)} started", DIM),
            )
        )
        theory = progress.load().get("theory", {})
        answered = sum(t["answered"] for t in theory.values())
        correct = sum(t["correct"] for t in theory.values())
        pct = f"{correct * 100 // answered}%" if answered else "—"
        self.query_one("#card-theory", Static).update(
            Text.assemble(
                ("theory accuracy\n", DIM),
                (pct, f"bold {GREEN}"),
                (f"\n{answered} answered · {len(theory)} topics", DIM),
            )
        )
        self.query_one("#card-rating", Static).update(
            Text.assemble(("rating\n", DIM), ("…", f"bold {GREEN}"), ("\nasking the server", DIM))
        )
        self._rating()

        menu = self.query_one("#home-next", OptionList)
        menu.clear_options()
        going = sorted(
            (s for s in sessions.values() if not s.finished), key=lambda s: -s.updated_at
        )
        by_id = {lab.id: lab for lab in labs}
        for s in going:
            lab = by_id.get(s.lab_id)
            if lab is None:
                continue
            m = lab.manifest
            menu.add_option(
                Option(
                    Text.assemble(
                        ("continue  ", GREEN),
                        (f"{m.short_id:<10}", f"bold {TEXT}"),
                        f"{m.title:<44}",
                        (f" {s.state.value} on {s.image}", DIM),
                    ),
                    id=m.id,
                )
            )
        fresh = sorted(
            (lab for lab in labs if lab.id not in sessions),
            key=lambda lab: (lab.manifest.difficulty, lab.manifest.estimated_minutes),
        )[:6]
        if going and fresh:
            menu.add_option(None)
        for lab in fresh:
            m = lab.manifest
            menu.add_option(
                Option(
                    Text.assemble(
                        ("next      ", DIM),
                        (f"{m.short_id:<10}", f"bold {TEXT}"),
                        f"{m.title:<44} ",
                        dots(m.difficulty),
                        (f" ~{m.estimated_minutes}m", DIM),
                    ),
                    id=m.id,
                )
            )
        if not menu.option_count:
            menu.add_option(Option(Text("Every lab is done. 2 opens the catalogue.", style=DIM)))

    @work(thread=True, exclusive=True, group="home-rating")
    def _rating(self) -> None:
        card = self.query_one("#card-rating", Static)
        if not data.signed_in():
            body = Text.assemble(
                ("rating\n", DIM), ("—", f"bold {DIM}"), ("\na signs in to be rated", DIM)
            )
            self.app.call_from_thread(card.update, body)
            return
        try:
            me = data.me()
        except data.ApiUnavailable:
            me = None
            body = Text.assemble(("rating\n", DIM), ("offline", f"bold {AMBER}"))
        else:
            if me is None:
                body = Text.assemble(
                    ("rating\n", DIM), ("—", "bold"), ("\n7 to choose a nick", DIM)
                )
            else:
                o = me["overall"]
                body = Text.assemble(
                    ("rating\n", DIM),
                    (str(o["rating"]), f"bold {GREEN}"),
                    (f" ± {o['rd']}", DIM),
                    ("\nprovisional" if o["provisional"] else f"\n{me['user']['nick']}", DIM),
                )
        self.app.call_from_thread(card.update, body)

    @on(OptionList.OptionSelected, "#home-next")
    def _chosen(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            _open_lab(self.app, event.option.id)


# ---------------------------------------------------------------------------------------------
# Labs
# ---------------------------------------------------------------------------------------------


class LabsSection(Section):
    label = "Labs"
    BINDINGS = [
        Binding("f", "filter", "Track filter"),
        Binding("u", "pull", "Pull a lab"),
    ]

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.track: str | None = None
        self._load_labs()

    def _load_labs(self) -> None:
        from norboten import rated

        # the rated labs this machine last heard of from the server: manifest and briefing only
        labs = [*lab_store.all_labs(), *rated.cached_labs()]
        self.labs = {lab.id: lab for lab in labs}
        self.tracks = [None, *sorted({lab.manifest.track.value for lab in self.labs.values()})]

    def compose(self) -> ComposeResult:
        yield Static("", id="labs-head", classes="h2")
        with Horizontal():
            yield DataTable(id="labs-table", cursor_type="row")
            with VerticalScroll(id="labs-preview"):
                yield Static("", id="labs-meta")
                yield Markdown("", id="labs-briefing")

    def on_mount(self) -> None:
        table = self.query_one("#labs-table", DataTable)
        # the title last: on a narrow terminal it is the column that runs off, not Status or Rated
        table.add_columns("Track", "Lab", "Level", "Time", "Status", "Rated", "Title")
        self.query_one("#labs-preview").border_title = "briefing"
        if data.signed_in():
            self._refresh_rated()

    @work(thread=True, exclusive=True, group="rated-catalogue")
    def _refresh_rated(self) -> None:
        """Ask the server which rated labs it grades. Offline, the last list stays."""
        from norboten import rated

        try:
            rated.refresh()
        except rated.RatedError:
            return
        self._load_labs()
        self.app.call_from_thread(self.refresh_data)

    def refresh_data(self) -> None:
        table = self.query_one("#labs-table", DataTable)
        keep = table.cursor_row
        table.clear()
        for lab in self.labs.values():
            m = lab.manifest
            if self.track and m.track.value != self.track:
                continue
            s = Session.load(m.id)
            status = Text("")
            if s:
                colour = GREEN if s.state == State.PASSED else AMBER if s.rated else TEXT
                status = Text(s.state.value, style=colour)
            table.add_row(
                m.track.value,
                m.short_id,
                dots(m.difficulty),
                f"{m.estimated_minutes}m",
                status,
                Text("+", style=f"bold {AMBER}") if m.rated else Text("−", style=DIM),
                m.title,
                key=m.id,
            )
        if table.row_count:
            table.move_cursor(row=min(keep, table.row_count - 1))
        rated_count = sum(1 for lab in self.labs.values() if lab.manifest.rated)
        head = Text.assemble(
            (f"{table.row_count} labs", f"bold {GREEN}"),
            (f" · {rated_count} rated" if rated_count else "", AMBER),
            (
                f"   track: {self.track or 'all'} · f to change · Enter opens a lab · u pulls one",
                DIM,
            ),
        )
        self.query_one("#labs-head", Static).update(head)

    def action_filter(self) -> None:
        i = self.tracks.index(self.track)
        self.track = self.tracks[(i + 1) % len(self.tracks)]
        self.refresh_data()

    def action_pull(self) -> None:
        """Fetch a published lab from the registry into ~/.norboten/labs — how an installed copy,
        with no checkout beside it, gets its labs."""
        from norboten.tui.modals import AskScreen

        def asked(answer: str | None) -> None:
            if answer:
                lab_id, _, version = answer.partition(":")
                self.app.note(f"pulling {lab_id}:{version or 'latest'}")
                self._pull(lab_id.strip(), version.strip() or "latest")

        self.app.push_screen(
            AskScreen(
                "Pull a published lab",
                "rhcsa-03-storage-and-lvm  or  rhcsa-03-storage-and-lvm:1.2.0",
                "Labs are published as OCI artifacts; the newest cached version is the one used.",
            ),
            asked,
        )

    @work(thread=True, exclusive=True, group="lab-pull")
    def _pull(self, lab_id: str, version: str) -> None:
        from norboten.oci import OciError

        try:
            lab = lab_store.pull(lab_id, version)
        except (lab_store.LabError, OciError, OSError) as e:
            self.app.call_from_thread(self.app.note, f"pull {lab_id} failed: {e}", RED)
            return
        m = lab.manifest
        self.app.call_from_thread(self.app.note, f"✓ {m.id} v{m.version} — {m.title}", GREEN)
        self._load_labs()
        self.app.call_from_thread(self.refresh_data)

    @on(DataTable.RowHighlighted, "#labs-table")
    def _preview(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None or event.row_key.value not in self.labs:
            return
        lab = self.labs[event.row_key.value]
        m = lab.manifest
        images = Text(", ").join(
            Text(i, style=GREEN if store.cached(i) else DIM) for i in m.base_images
        )
        self.query_one("#labs-meta", Static).update(
            Text.assemble(
                (m.title, f"bold {GREEN}"),
                "\n",
                ("RATED · judged on the server · " if m.rated else "", AMBER),
                (f"{m.id} v{m.version} · {len(m.checks)} checks · ", DIM),
                ("reboot-graded" if m.reboot_required else "no reboot", DIM),
                "\nimages: ",
                images,
                ("   (green = downloaded)", DIM),
                "\ntopics: ",
                (", ".join(m.topics), TEXT),
            )
        )
        self.query_one("#labs-briefing", Markdown).update(lab.briefing)

    @on(DataTable.RowSelected, "#labs-table")
    def _open(self, event: DataTable.RowSelected) -> None:
        _open_lab(self.app, event.row_key.value)


# ---------------------------------------------------------------------------------------------
# Theory
# ---------------------------------------------------------------------------------------------


class TheorySection(Section):
    label = "Theory"
    BINDINGS = [
        Binding("r", "toggle_rated", "Timed/untimed"),
        Binding("g", "draft", "Draft questions"),
    ]

    rated = False
    drafting = False

    def compose(self) -> ComposeResult:
        yield Static("", id="theory-mode", classes="h2")
        with Horizontal():
            yield DataTable(id="banks", cursor_type="row")
            yield Static("", id="bank-about", classes="panel")

    def on_mount(self) -> None:
        from norboten import rated
        from norboten.quiz import bank

        self.published = {(b.lab_id or b.topic): b for b in bank.all_banks()}
        self.banks = dict(self.published)
        self.rated_banks = {f"rated:{b['topic']}": b for b in rated.cached_banks()}
        if data.signed_in():
            self._refresh_rated()
        self.query_one("#banks", DataTable).add_columns(
            "Bank", "Kind", "Qs", "Done", "Right", "Streak"
        )
        self.query_one("#bank-about").border_title = "about"

    @work(thread=True, exclusive=True, group="rated-banks")
    def _refresh_rated(self) -> None:
        from norboten import rated

        try:
            banks = rated.refresh_banks()
        except rated.RatedError:
            return
        self.rated_banks = {f"rated:{b['topic']}": b for b in banks}
        self.app.call_from_thread(self.refresh_data)

    def refresh_data(self) -> None:
        from norboten.quiz import bank

        self.banks = {**self.published, **{b.topic: b for b in bank.own_banks()}}
        stats = progress.load().get("theory", {})
        table = self.query_one("#banks", DataTable)
        keep = table.cursor_row
        table.clear()
        for key, rb in self.rated_banks.items():
            s = stats.get(rb["topic"])
            table.add_row(
                rb["title"],
                Text("rated", style=AMBER),
                str(rb["questions"]),
                str(s["answered"]) if s else "0",
                Text("server-graded", style=DIM),
                str(s["best_streak"]) if s else "—",
                key=key,
            )
        order = sorted(self.banks.items(), key=lambda kv: (kv[1].lab_id is not None, kv[0]))
        for key, b in order:
            s = stats.get(b.topic)
            acc = Text("not started", style=DIM)
            if s and s["answered"]:
                pct = s["correct"] * 100 // s["answered"]
                acc = Text(f"{pct}%", style=GREEN if pct >= 70 else AMBER if pct >= 40 else RED)
            table.add_row(
                b.bank.title.removeprefix("Theory: "),
                "yours" if b.own else b.lab_id or "topic",
                str(len(b.bank.questions)),
                str(s["answered"]) if s else "0",
                acc,
                str(s["best_streak"]) if s else "—",
                key=key,
            )
        if table.row_count:
            table.move_cursor(row=min(keep, table.row_count - 1))
        self._mode()

    def _mode(self) -> None:
        total = sum(len(b.bank.questions) for b in self.banks.values())
        self.query_one("#theory-mode", Static).update(
            Text.assemble(
                (f"{len(self.banks)} banks · {total} questions   ", f"bold {GREEN}"),
                (
                    " TIMED " if self.rated else " untimed ",
                    f"bold {BG} on {AMBER if self.rated else DIM}",
                ),
                (
                    "  every question against the clock — unrated banks never rate"
                    if self.rated
                    else "  take your time"
                ),
                (
                    f"   {len(self.rated_banks)} rated banks, always timed and graded on the server"
                    if self.rated_banks
                    else "",
                    AMBER,
                ),
                ("   r to switch · g drafts more · Enter starts", DIM),
            )
        )

    def action_toggle_rated(self) -> None:
        self.rated = not self.rated
        self._mode()

    @on(DataTable.RowHighlighted, "#banks")
    def _about(self, event: DataTable.RowHighlighted) -> None:
        key = event.row_key.value if event.row_key else ""
        rb = self.rated_banks.get(key)
        if rb is not None:
            self.query_one("#bank-about", Static).update(
                Text.assemble(
                    (rb["title"], f"bold {GREEN}"),
                    "\n\n",
                    " ".join(rb["description"].split()),
                    "\n\n",
                    ("topics   ", DIM),
                    ", ".join(rb["topics"]),
                    "\n",
                    ("a run    ", DIM),
                    f"{rb['questions']} questions",
                    (
                        "\n\nA rated bank: questions come from the server one at a time, every "
                        "one against its clock, and the server grades them. A run moves your "
                        "topic rating. Needs a sign-in.",
                        AMBER,
                    ),
                )
            )
            return
        b = self.banks.get(key)
        if b is None:
            return
        kinds: dict[str, int] = {}
        for q in b.bank.questions:
            kinds[q.type] = kinds.get(q.type, 0) + 1
        verified = sum(1 for q in b.bank.questions if getattr(q, "verify", None))
        self.query_one("#bank-about", Static).update(
            Text.assemble(
                (b.bank.title, f"bold {GREEN}"),
                "\n\n",
                " ".join(b.bank.description.split()),
                "\n\n",
                ("topics   ", DIM),
                ", ".join(b.bank.topics),
                "\n",
                ("kinds    ", DIM),
                ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())),
                "\n",
                ("verified ", DIM),
                f"{verified} executed in a sandbox",
                (
                    "\n\nyour own questions: practice only, never rated, read by nobody else"
                    if b.own
                    else ""
                ),
            )
        )

    @on(DataTable.RowSelected, "#banks")
    def _start(self, event: DataTable.RowSelected) -> None:
        from norboten.tui.quiz import QuizScreen

        key = event.row_key.value
        if key in self.rated_banks:
            self._start_rated(self.rated_banks[key])
            return
        b = self.banks[key]
        if b.own and self.rated:
            self.app.note("your own questions are practice only; starting untimed", AMBER)
        self.app.push_screen(
            QuizScreen(
                b.bank.title,
                b.topic,
                b.bank.questions,
                rated=self.rated and not b.own,
                topics=b.bank.topics,
            )
        )

    @work(thread=True, exclusive=True, group="rated-quiz")
    def _start_rated(self, rb: dict) -> None:
        from norboten import rated
        from norboten.quiz.remote import RemoteQuiz
        from norboten.tui.quiz import QuizScreen

        try:
            quiz = RemoteQuiz.start(rb["topic"])
        except rated.RatedError as e:
            self.app.call_from_thread(self.app.note, str(e), RED)
            return
        screen = QuizScreen(rb["title"], rb["topic"], [], topics=rb["topics"], quiz=quiz)
        self.app.call_from_thread(self.app.push_screen, screen)

    def action_draft(self) -> None:
        from norboten.questions import pipeline
        from norboten.tui.modals import DraftScreen

        table = self.query_one("#banks", DataTable)
        if not table.row_count:
            return
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        source = self.banks.get(key)
        if source is None:
            return
        if self.drafting:
            self.app.note("already drafting; wait for it to finish", AMBER)
            return

        def chosen(answer: dict | None) -> None:
            if answer:
                self.drafting = True
                self._draft(source, answer["count"], answer["about"])

        title = source.bank.title.removeprefix("Theory: ")
        self.app.push_screen(DraftScreen(title, pipeline.choose_models()), chosen)

    @work(thread=True, exclusive=True, group="theory-draft")
    def _draft(self, source, count: int, about: str | None) -> None:
        from norboten.questions import own, providers

        call = self.app.call_from_thread
        call(self.app.note, f"drafting {count} question(s) on {source.bank.title}")

        def seen(a) -> None:
            if a.accepted:
                call(self.app.note, f"  {a.number}/{count} accepted: {a.prompt[:70]}", GREEN)
            else:
                call(self.app.note, f"  {a.number}/{count} rejected at {a.stage}: {a.reason[:70]}")

        try:
            attempts = own.draft_more(source, count=count, about=about, on_attempt=seen)
        except providers.ProviderError as e:
            call(self.app.note, f"drafting failed: {e}", RED)
            attempts = []
        finally:
            self.drafting = False
        kept = sum(a.accepted for a in attempts)
        if attempts:
            call(
                self.app.note,
                f"{kept} of {len(attempts)} kept in your own bank" if kept else "none passed",
                GREEN if kept else AMBER,
            )
        call(self.refresh_data)


# ---------------------------------------------------------------------------------------------
# Journals
# ---------------------------------------------------------------------------------------------


class JournalsSection(Section):
    label = "Journals"
    BINDINGS = [Binding("e", "export", "Export PDF")]

    def compose(self) -> ComposeResult:
        yield Static("", id="journals-head", classes="h2")
        with Horizontal():
            yield DataTable(id="journals-table", cursor_type="row")
            with VerticalScroll(id="journal-view"):
                yield Markdown("", id="journal-body")

    def on_mount(self) -> None:
        from norboten.journal import all_journals

        self.journals = {j.id: j for j in all_journals()}
        table = self.query_one("#journals-table", DataTable)
        table.add_columns("Journal", "Read")
        for j in self.journals.values():
            style = {"lab": TEXT, "note": AMBER}.get(j.kind, f"bold {GREEN}")
            name = Text(_clip(j.id, 28), style=style)
            table.add_row(name, f"{j.minutes}m", key=j.id)
        self.query_one("#journal-view").border_title = "journal"
        words = sum(j.words for j in self.journals.values())
        self.query_one("#journals-head", Static).update(
            Text.assemble(
                (f"{len(self.journals)} journals", f"bold {GREEN}"),
                (
                    f" · {words:,} words · topics in green, notes in amber   Enter reads · e "
                    "exports a PDF",
                    DIM,
                ),
            )
        )
        self._shown = ""
        self._pending = ""

    def _current(self):
        table = self.query_one("#journals-table", DataTable)
        if not table.row_count:
            return None
        key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        return self.journals.get(key)

    @on(DataTable.RowHighlighted, "#journals-table")
    def _preview(self, event: DataTable.RowHighlighted) -> None:
        # A journal is thousands of words; render it once the cursor stops moving.
        self._pending = event.row_key.value if event.row_key else ""
        self.set_timer(0.25, self._render_pending)

    def _render_pending(self) -> None:
        j = self.journals.get(self._pending)
        if j is None or j.id == self._shown:
            return
        self._shown = j.id
        self.query_one("#journal-view").border_title = f"{j.title} · {', '.join(j.topics)}"
        self.query_one("#journal-body", Markdown).update(j.body)
        self.query_one("#journal-view").scroll_home(animate=False)

    @on(DataTable.RowSelected, "#journals-table")
    def _read(self, event: DataTable.RowSelected) -> None:
        from norboten.tui.lab import JournalScreen

        self.app.push_screen(JournalScreen(self.journals[event.row_key.value]))

    def action_export(self) -> None:
        from norboten.tui.lab import export_pdf

        j = self._current()
        if j is not None:
            export_pdf(self.app, j)


# ---------------------------------------------------------------------------------------------
# Play
# ---------------------------------------------------------------------------------------------


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _cast_label(cast: data.Cast) -> Text:
    return Text.assemble(f"  {_clip(cast.title, 25):<25} ", (duration(cast.duration), DIM))


class PlaySection(Section):
    label = "Play"
    BINDINGS = [Binding("R", "reload", "Reload")]

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="play-left"):
                yield OptionList(id="play-sources")
                yield OptionList(id="play-commands")
            yield TermPlayer(id="player")

    def on_mount(self) -> None:
        self.casts: dict[str, data.Cast | dict] = {}
        self.query_one("#play-sources").border_title = "recordings"
        self.query_one("#play-commands").border_title = "commands"

    def refresh_data(self) -> None:
        if not self.casts:
            self.action_reload()

    def action_reload(self) -> None:
        sources = self.query_one("#play-sources", OptionList)
        sources.clear_options()
        self.casts.clear()

        def heading(label: str) -> None:
            sources.add_option(Option(Text(label, style=f"bold {DIM}"), disabled=True))

        here = data.local_casts()
        heading("RECORDED HERE")
        if not here:
            sources.add_option(Option(Text("  none yet — p on a lab", style=DIM), disabled=True))
        for n, cast in enumerate(here):
            key = f"here-{n}"
            self.casts[key] = cast
            sources.add_option(Option(_cast_label(cast), id=key))
        shipped = data.shipped_casts()
        if shipped:
            heading("SHIPPED WITH NORBOTEN")
        for n, cast in enumerate(shipped):
            key = f"shipped-{n}"
            self.casts[key] = cast
            sources.add_option(Option(_cast_label(cast), id=key))
        heading("ON THE SITE")
        self._site()

    @work(thread=True, exclusive=True, group="play-site")
    def _site(self) -> None:
        sources = self.query_one("#play-sources", OptionList)
        try:
            cards = data.live(limit=12)
        except data.ApiUnavailable:
            option = Option(Text("  offline — the site is out of reach", style=DIM), disabled=True)
            self.app.call_from_thread(sources.add_option, option)
            return
        rows = [("● ", c) for c in cards.get("live", [])] + [
            ("  ", c) for c in cards.get("recent", [])
        ]
        if not rows:
            option = Option(Text("  nobody right now", style=DIM), disabled=True)
            self.app.call_from_thread(sources.add_option, option)
        for mark, card in rows:
            key = f"site-{card['session_id']}"
            self.casts[key] = card
            label = Text.assemble(
                (mark, RED if mark.strip() else ""),
                f"{card.get('nick', '?')[:12]:<12} {card.get('lab_id', '')[:18]}",
            )
            self.app.call_from_thread(sources.add_option, Option(label, id=key))

    @on(OptionList.OptionSelected, "#play-sources")
    def _pick(self, event: OptionList.OptionSelected) -> None:
        chosen = self.casts.get(event.option.id or "")
        if isinstance(chosen, data.Cast):
            self._load(chosen)
        elif isinstance(chosen, dict):
            self._fetch(chosen)

    @work(thread=True, exclusive=True, group="play-fetch")
    def _fetch(self, card: dict) -> None:
        try:
            cast = data.site_cast(card)
        except data.ApiUnavailable as e:
            self.app.call_from_thread(self.app.notify, str(e), severity="warning")
            return
        self.app.call_from_thread(self._load, cast)

    def _load(self, cast: data.Cast) -> None:
        player = self.query_one(TermPlayer)
        player.load(cast)
        commands = self.query_one("#play-commands", OptionList)
        commands.clear_options()
        touched = {c.get("command") for c in cast.changes}
        for n, c in enumerate(cast.commands):
            label = Text.assemble(
                ("✎ " if c["text"] in touched else "  ", AMBER),
                (f"{duration(c['at']):>6} ", DIM),
                (c["text"], TEXT),
            )
            commands.add_option(Option(label, id=str(n)))
        commands.border_subtitle = f"{len(cast.commands)} · ✎ changed a file"
        player.focus()

    @on(TermPlayer.Moved)
    def _moved(self, event: TermPlayer.Moved) -> None:
        commands = self.query_one("#play-commands", OptionList)
        if 0 <= event.command < commands.option_count:
            commands.highlighted = event.command

    @on(OptionList.OptionSelected, "#play-commands")
    def _seek(self, event: OptionList.OptionSelected) -> None:
        player = self.query_one(TermPlayer)
        if player.cast and event.option.id is not None:
            player.playing = False
            player.seek(player.cast.commands[int(event.option.id)]["at"] + 0.05)


# ---------------------------------------------------------------------------------------------
# Profiles: You, and anyone's from the boards
# ---------------------------------------------------------------------------------------------


class ProfileView(VerticalScroll):
    """The web profile in a terminal: a year of work first, then by topic, then attempts."""

    def compose(self) -> ComposeResult:
        yield Static("", classes="profile-head")
        yield Static(Text("A year of work", style=f"bold {GREEN}"), classes="h2")
        yield Heatmap({}, [], id="heatmap")
        with Horizontal(classes="profile-topics"):
            with Vertical():
                yield Static(Text("By topic", style=f"bold {GREEN}"), classes="h2")
                yield Static("", classes="bars")
            with Vertical(classes="strongest-box"):
                yield Static(Text("Strongest", style=f"bold {GREEN}"), classes="h2")
                yield Static("", classes="strongest")
        yield Static(Text("Recent attempts", style=f"bold {GREEN}"), classes="h2")
        yield DataTable(classes="attempts", cursor_type="row")

    def on_mount(self) -> None:
        self.history: list[dict] = []
        self.query_one(".attempts", DataTable).add_columns(
            "When", "Lab", "Kind", "Result", "Score", "Took", "Rating"
        )

    def show(self, profile: dict) -> None:
        self.query_one(".profile-head", Static).update(profile_header(profile))
        self.history = sorted(profile.get("history", []), key=lambda a: -a["started_at"])
        self.query_one(Heatmap).update_data(profile.get("contributions", {}), self.history)
        self.radar = profile.get("radar", [])
        self._bars()
        self.call_after_refresh(self._bars)  # again, once the layout has given the bars their width
        self.query_one(".strongest", Static).update(strongest(profile.get("radar", [])))
        table = self.query_one(".attempts", DataTable)
        table.clear()
        for n, a in enumerate(self.history[:50]):
            moved = sum((a.get("rating_delta") or {}).values())
            table.add_row(
                datetime.fromtimestamp(a["started_at"]).strftime("%d %b %H:%M"),
                a["lab_id"],
                a.get("kind", "lab"),
                Text("passed", style=GREEN) if a["passed"] else Text("not yet", style=RED),
                f"{a['score_percent']}%",
                duration(a["duration_seconds"]),
                Text(f"{moved:+.0f}", style=GREEN if moved >= 0 else RED)
                if a.get("rated")
                else Text("practice", style=DIM),
                key=str(n),
            )

    def on_resize(self) -> None:
        if getattr(self, "radar", None):
            self._bars()

    def _bars(self) -> None:
        bars = self.query_one(".bars", Static)
        room = bars.size.width or 80
        bars.update(topic_bars(self.radar, width=max(6, min(28, room - 46))))

    @on(DataTable.RowSelected, ".attempts")
    def _attempt(self, event: DataTable.RowSelected) -> None:
        from norboten.tui.modals import AttemptScreen

        self.app.push_screen(AttemptScreen(self.history[int(event.row_key.value)]))


class ProfileScreen(Screen):
    """Someone's profile, opened from a board."""

    BINDINGS = [Binding("escape,q", "app.pop_screen", "Back")]

    def __init__(self, nick: str) -> None:
        super().__init__()
        self.nick = nick

    def compose(self) -> ComposeResult:
        yield TopBar()
        yield Static(Text(f"loading {self.nick}…", style=DIM), id="profile-status")
        yield ProfileView()
        yield Footer()

    def on_mount(self) -> None:
        self.load()

    @work(thread=True, exclusive=True)
    def load(self) -> None:
        status = self.query_one("#profile-status", Static)
        try:
            profile = data.profile(self.nick)
        except data.ApiUnavailable as e:
            self.app.call_from_thread(status.update, Text(f"offline: {e}", style=AMBER))
            return
        self.app.call_from_thread(status.update, "")
        self.app.call_from_thread(self.query_one(ProfileView).show, profile)


# ---------------------------------------------------------------------------------------------
# Ratings
# ---------------------------------------------------------------------------------------------


class RatingsSection(Section):
    label = "Ratings"

    def compose(self) -> ComposeResult:
        yield Static("", id="board-head", classes="h2")
        with Horizontal():
            yield OptionList(
                Option("Overall", id="overall"),
                None,
                *(Option(t.title, id=t.slug) for t in TOPICS),
                id="board-topics",
            )
            yield DataTable(id="board", cursor_type="row")

    def on_mount(self) -> None:
        self.topic: str | None = None
        self.query_one("#board", DataTable).add_columns(
            "#", "Player", "Country", "Rating", "±", "Conservative"
        )
        self.query_one("#board-topics").border_title = "board"

    def refresh_data(self) -> None:
        self.load()

    @on(OptionList.OptionHighlighted, "#board-topics")
    def _topic(self, event: OptionList.OptionHighlighted) -> None:
        topic = None if event.option.id == "overall" else event.option.id
        if topic != self.topic:
            self.topic = topic
            self.load()

    @on(OptionList.OptionSelected, "#board-topics")
    def _to_board(self) -> None:
        self.query_one("#board").focus()

    @work(thread=True, exclusive=True, group="board")
    def load(self) -> None:
        head = self.query_one("#board-head", Static)
        name = next((t.title for t in TOPICS if t.slug == self.topic), "Overall")
        self.app.call_from_thread(head.update, Text(f"{name} · loading…", style=DIM))
        try:
            rows = data.leaderboard(self.topic)
        except data.ApiUnavailable as e:
            self.app.call_from_thread(
                head.update,
                Text.assemble(
                    ("offline  ", f"bold {AMBER}"),
                    (f"{e}. The boards live on the server; labs and theory work without it.", DIM),
                ),
            )
            return
        self.app.call_from_thread(self._fill, name, rows)

    def _fill(self, name: str, rows: list[dict]) -> None:
        table = self.query_one("#board", DataTable)
        table.clear()
        for r in rows:
            table.add_row(
                str(r["rank"]),
                Text(r["nick"], style=f"bold {GREEN}" if r["rank"] <= 3 else TEXT),
                f"{flag(r['country'])} {r['country']}",
                Text(str(r["rating"]), style="bold"),
                Text(str(r["rd"]), style=AMBER if r.get("provisional") else DIM),
                str(r["conservative"]),
                key=r["nick"],
            )
        self.query_one("#board-head", Static).update(
            Text.assemble(
                (name, f"bold {GREEN}"),
                (f" · {len(rows)} players · sorted on rating − 2·RD · Enter opens a profile", DIM),
            )
        )

    @on(DataTable.RowSelected, "#board")
    def _open(self, event: DataTable.RowSelected) -> None:
        self.app.push_screen(ProfileScreen(event.row_key.value))


# ---------------------------------------------------------------------------------------------
# You
# ---------------------------------------------------------------------------------------------


class YouSection(Section):
    label = "You"

    def compose(self) -> ComposeResult:
        yield Static("", id="you-status", classes="h2")
        with Vertical(id="you-claim"):
            yield Static(
                Text(
                    "Choose the public nick your rating appears under. The nick is chosen once; "
                    "the country can be changed later. Both start from a guess — your GitHub "
                    "login, and the country your address is in — which is never saved unless you "
                    "claim it.",
                    style=DIM,
                )
            )
            with Horizontal(classes="form-row"):
                yield Input(placeholder="nick: 3–20 of a-z 0-9 - _", id="nick")
                yield Input(placeholder="country, e.g. PL", id="country", max_length=2)
                yield Button("Claim", id="claim", variant="success")
        with Horizontal(id="you-country", classes="form-row"):
            yield Static(Text("Country", style=DIM), classes="form-label")
            yield Input(placeholder="e.g. PL", id="country-change", max_length=2)
            yield Button("Change", id="move")
        yield ProfileView(id="you-profile")

    def on_mount(self) -> None:
        self.query_one("#you-claim").display = False
        self.query_one("#you-country").display = False
        self.query_one("#you-profile").display = False

    def refresh_data(self) -> None:
        self.load()

    @work(thread=True, exclusive=True, group="you")
    def load(self) -> None:
        status = self.query_one("#you-status", Static)
        if not data.signed_in():
            self.app.call_from_thread(self._mode, None)
            self.app.call_from_thread(
                status.update,
                Text.assemble(
                    ("Not signed in.\n\n", f"bold {TEXT}"),
                    (
                        "Nothing needs an account: labs, theory, journals and recordings all work "
                        "offline. Signing in adds a rating per topic, a public profile with a year "
                        "of work, and a place on the boards.\n\n",
                        DIM,
                    ),
                    (" a ", f"bold {BG} on {GREEN}"),
                    (" sign in", TEXT),
                ),
            )
            return
        try:
            me = data.me()
        except data.ApiUnavailable as e:
            self.app.call_from_thread(self._mode, None)
            self.app.call_from_thread(status.update, Text(f"offline: {e}", style=AMBER))
            return
        if me is None:
            who = data.identity() or {}
            nick = data.nick_draft(who.get("github_login", ""))
            country = data.guess_country()
            self.app.call_from_thread(self._mode, "claim")
            self.app.call_from_thread(self._draft, nick, country)
            self.app.call_from_thread(
                status.update, Text("Signed in — one step left.", style=f"bold {GREEN}")
            )
            return
        self.app.call_from_thread(self._mode, "profile")
        self.app.call_from_thread(status.update, "")
        self.app.call_from_thread(self.query_one("#you-profile", ProfileView).show, me)
        self.app.call_from_thread(self._draft_country, me["user"]["country"])

    def _draft(self, nick: str, country: str) -> None:
        """Only into empty fields: whatever the learner already typed wins."""
        for field, value in (("#nick", nick), ("#country", country)):
            box = self.query_one(field, Input)
            if not box.value and value:
                box.value = value

    def _draft_country(self, country: str) -> None:
        box = self.query_one("#country-change", Input)
        if not box.has_focus:
            box.value = country

    def _mode(self, mode: str | None) -> None:
        self.query_one("#you-claim").display = mode == "claim"
        self.query_one("#you-country").display = mode == "profile"
        self.query_one("#you-profile").display = mode == "profile"
        self.query_one("#you-status").display = mode != "profile"

    @on(Button.Pressed, "#claim")
    @on(Input.Submitted, "#nick, #country")
    def _claim(self) -> None:
        nick = self.query_one("#nick", Input).value.strip().lower()
        country = self.query_one("#country", Input).value.strip()
        if not nick or not country:
            self.app.notify("a nick and a two-letter country, please", severity="warning")
            return
        self._send_claim(nick, country)

    @work(thread=True, exclusive=True, group="claim")
    def _send_claim(self, nick: str, country: str) -> None:
        try:
            data.claim(nick, country)
        except (data.NickTaken, ValueError, data.ApiUnavailable) as e:
            self.app.call_from_thread(self.app.notify, str(e), severity="error")
            return
        self.app.call_from_thread(self.app.notify, f"✓ you are {nick}")
        self.app.call_from_thread(self.app.refresh_account)
        self.load()

    @on(Button.Pressed, "#move")
    @on(Input.Submitted, "#country-change")
    def _move(self) -> None:
        country = self.query_one("#country-change", Input).value.strip()
        if len(country) != 2:
            self.app.notify("a two-letter country, please", severity="warning")
            return
        self._send_country(country)

    @work(thread=True, exclusive=True, group="claim")
    def _send_country(self, country: str) -> None:
        try:
            data.set_country(country)
        except (ValueError, data.ApiUnavailable) as e:
            self.app.call_from_thread(self.app.notify, str(e), severity="error")
            return
        self.app.call_from_thread(self.app.notify, f"✓ country {country.upper()}")
        self.app.call_from_thread(self.app.refresh_account)
        self.load()


# ---------------------------------------------------------------------------------------------
# System
# ---------------------------------------------------------------------------------------------


class SystemSection(Section):
    label = "System"
    BINDINGS = [
        Binding("p", "pull", "Pull image"),
        Binding("x", "remove", "Remove image"),
        Binding("s", "app.setup", "Setup"),
        Binding("u", "update", "Update norboten"),
        Binding("X", "uninstall", "Uninstall", show=False),
        Binding("m", "tutor_model", "Tutor model"),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(Text("Doctor", style=f"bold {GREEN}"), classes="h2")
            yield Static(Text("checking…", style=DIM), id="doctor-full")
            yield Static(Text("Base images", style=f"bold {GREEN}"), classes="h2")
            yield DataTable(id="images", cursor_type="row")
            yield ProgressBar(id="pull-bar", show_eta=True)
            yield Static(Text("p pulls the selected image · x removes it", style=DIM))
            yield Static(Text("This installation", style=f"bold {GREEN}"), classes="h2")
            yield Static("", id="about")

    def on_mount(self) -> None:
        self.query_one("#images", DataTable).add_columns(
            "Image", "Distro", "Tracks", "Downloaded", "Used by"
        )
        self.query_one("#pull-bar").display = False
        self.pulling = False

    def refresh_data(self) -> None:
        self.show_doctor(getattr(self.app, "findings", None))
        self._images()
        self._about()

    def show_doctor(self, findings) -> None:
        if findings is None:
            return
        from norboten import doctor

        out = Text()
        for f in findings:
            mark, colour = STATUS_MARK[f.status]
            out.append(f"{mark} ", style=f"bold {colour}")
            out.append(f"{f.name:<16}", style=f"bold {TEXT}")
            out.append(f"{f.detail}\n", style=TEXT)
            if f.fix:
                out.append(f"  → {f.fix}\n", style=DIM)
        ready = doctor.ready(findings)
        out.append("\n")
        out.append(
            " READY " if ready else " NOT READY ", style=f"bold {BG} on {GREEN if ready else RED}"
        )
        out.append(
            "  labs can run on this machine" if ready else "  fix the items marked ✗, then d",
            style=DIM,
        )
        self.query_one("#doctor-full", Static).update(out)

    def _images(self) -> None:
        from norboten.labs.manifest import default_registry
        from norboten.models import format_size

        registry = default_registry()
        labs = lab_store.all_labs()
        table = self.query_one("#images", DataTable)
        keep = table.cursor_row
        table.clear()
        for image_id, image in registry.images.items():
            local = store.cached(image_id)
            used = [lab.manifest.short_id for lab in labs if image_id in lab.manifest.base_images]
            table.add_row(
                image_id,
                image.distro,
                ", ".join(t.value for t in image.tracks),
                Text(format_size(local.size_bytes), style=GREEN)
                if local
                else Text("no", style=DIM),
                ", ".join(used) or "—",
                key=image_id,
            )
        if table.row_count:
            table.move_cursor(row=min(keep, table.row_count - 1))

    def _about(self) -> None:
        from norboten.models import format_size
        from norboten.paths import norboten_home, repo_root
        from norboten.tutor.client import base_url

        on_disk = sum(i.size_bytes for i in store.list_cached())
        from norboten import selfmanage

        latest = getattr(self.app, "latest", None)
        if selfmanage.is_newer(latest):
            version = Text.assemble(
                f"norboten {__version__}  ", (f"{latest} is out — u updates", f"bold {GREEN}")
            )
        elif latest:
            version = Text.assemble(f"norboten {__version__}  ", ("the newest", DIM))
        else:
            version = Text(f"norboten {__version__}")
        rows = (
            ("version", version),
            ("home", str(norboten_home())),
            ("images", f"{store.images_dir()} · {format_size(on_disk)}"),
            ("checkout", str(repo_root() or "— (installed package)")),
            ("api", base_url()),
            ("tutor", _tutor_line()),
            ("account", "signed in" if data.signed_in() else "not signed in"),
        )
        out = Text()
        for label, value in rows:
            out.append(f"{label:<10}", style=DIM)
            out.append(value if isinstance(value, Text) else Text(value, style=TEXT))
            out.append("\n")
        self.query_one("#about", Static).update(out)

    def action_update(self) -> None:
        from norboten import selfmanage
        from norboten.tui.modals import ConfirmScreen

        latest = getattr(self.app, "latest", None)
        if not selfmanage.is_newer(latest):
            self.app.note(
                f"norboten {__version__} is the newest" if latest else "cannot reach PyPI to check"
            )
            return
        try:
            selfmanage.require_receipt()
        except selfmanage.SelfManageError as e:
            self.app.note(str(e), RED)
            return

        def confirmed(yes: bool | None) -> None:
            if yes:
                self.app.exit("update")

        self.app.push_screen(
            ConfirmScreen(
                f"Update to norboten {latest}?",
                "norboten closes, uv installs the new version, and norboten opens again. "
                "Lab VMs keep running.",
                danger=False,
            ),
            confirmed,
        )

    def action_tutor_model(self) -> None:
        from norboten import settings
        from norboten.tui.modals import ModelScreen
        from norboten.tutor import models

        current = str(settings.load().get("tutor_model") or models.AUTO)

        def chosen(model: str | None) -> None:
            if model:
                models.pin(model)
                self.app.note(f"the tutor and the review use {model}", GREEN)
                self._about()

        self.app.push_screen(ModelScreen(models.available(), current), chosen)

    def action_uninstall(self) -> None:
        from norboten import selfmanage
        from norboten.models import format_size
        from norboten.tui.modals import ConfirmScreen

        try:
            selfmanage.require_receipt()
            plan = selfmanage.removal()
        except selfmanage.SelfManageError as e:
            self.app.note(str(e), RED)
            return
        machines = f"{len(plan.machines)} lab machines, " if plan.machines else ""
        detail = (
            f"This removes {machines}{plan.home} ({format_size(plan.home_bytes)}: images, "
            "sessions, recordings, sign-in) and the program. norboten closes first."
        )

        def confirmed(yes: bool | None) -> None:
            if yes:
                self.app.exit("uninstall")

        self.app.push_screen(ConfirmScreen("Uninstall norboten?", detail), confirmed)

    def _selected(self) -> str | None:
        table = self.query_one("#images", DataTable)
        if not table.row_count:
            return None
        return table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value

    def action_pull(self) -> None:
        image_id = self._selected()
        if image_id is None or self.pulling:
            return
        self.pulling = True
        bar = self.query_one("#pull-bar", ProgressBar)
        bar.update(total=None, progress=0)
        bar.display = True
        self.app.note(f"pulling {image_id}")
        self._pull(image_id)

    @work(thread=True, exclusive=True, group="pull")
    def _pull(self, image_id: str) -> None:
        bar = self.query_one("#pull-bar", ProgressBar)
        started = time.monotonic()

        def advance(n: int, total: int) -> None:
            def update() -> None:
                if total and bar.total != total:
                    bar.update(total=total)
                bar.advance(n)

            self.app.call_from_thread(update)

        try:
            img = store.pull(image_id, progress=advance)
        except Exception as e:
            self.app.call_from_thread(self.app.note, f"pull {image_id} failed: {e}", RED)
        else:
            took = time.monotonic() - started
            self.app.call_from_thread(
                self.app.note, f"✓ {image_id} ({img.source}, {took:.0f}s)", GREEN
            )
        finally:
            self.pulling = False
            self.app.call_from_thread(setattr, bar, "display", False)
            self.app.call_from_thread(self._images)
            self.app.call_from_thread(self._about)

    def action_remove(self) -> None:
        from norboten.tui.modals import ConfirmScreen

        image_id = self._selected()
        if image_id is None or not store.cached(image_id):
            return

        def confirmed(yes: bool | None) -> None:
            if yes:
                store.remove(image_id)
                self.app.note(f"removed {image_id}")
                self._images()
                self._about()

        self.app.push_screen(
            ConfirmScreen(
                f"Remove {image_id}?", "Labs that use it download it again on their next start."
            ),
            confirmed,
        )


def _tutor_line() -> str:
    from norboten import settings

    pinned = str(settings.load().get("tutor_model") or "auto")
    return f"{pinned} · m changes it"


SECTIONS: tuple[tuple[str, str, type[Section]], ...] = (
    ("home", "Home", HomeSection),
    ("labs", "Labs", LabsSection),
    ("theory", "Theory", TheorySection),
    ("journals", "Journals", JournalsSection),
    ("play", "Play", PlaySection),
    ("ratings", "Ratings", RatingsSection),
    ("you", "You", YouSection),
    ("system", "System", SystemSection),
)
