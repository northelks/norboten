"""A theory run: one question at a time, with the explanation after every answer."""

from __future__ import annotations

from collections.abc import Sequence

from rich.syntax import Syntax
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Footer,
    ProgressBar,
    RadioButton,
    RadioSet,
    SelectionList,
    Static,
)

from norboten import progress
from norboten.models import Question
from norboten.quiz.session import QuizSession
from norboten.tui.theme import DIM, GREEN, RED
from norboten.tui.widgets import TopBar


class QuizScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("enter", "submit", "Answer", priority=True),
        Binding("n", "next", "Next"),
        *(Binding(str(i), f"toggle({i})", show=False) for i in range(1, 7)),
    ]

    def __init__(
        self,
        title: str,
        topic: str,
        questions: list[Question],
        seed=None,
        *,
        rated: bool = False,
        topics: Sequence[str] = (),
        quiz=None,
    ):
        """`rated` on a published bank means timed, at exam pace — it never rates; a rated bank
        arrives as `quiz`, a `RemoteQuiz` the server grades (docs/quiz-spec.md §6)."""
        super().__init__()
        self.title_text = title
        self.topics = list(topics)
        self.quiz = quiz or QuizSession.start(topic, questions, seed=seed, rated=rated)
        self.remote = quiz is not None
        self.reported = False

    def compose(self) -> ComposeResult:
        yield TopBar()
        yield Static(self.title_text, classes="title")
        yield Static("", id="quiz-bar")
        yield ProgressBar(total=len(self.quiz.questions), show_eta=False, id="quizprogress")
        with VerticalScroll():
            yield Static("", id="question")
            yield Static("", id="question-code")
            yield Vertical(id="choices")
            yield Static("", id="feedback")
        yield Footer()

    async def on_mount(self) -> None:
        await self._render_question()
        if self.quiz.rated:
            self.set_interval(0.25, self._tick)

    def _tick(self) -> None:
        """The clock. When it runs out the question is answered for you — wrongly."""
        if self.quiz.finished or self.quiz.awaiting_next:
            return
        if self.quiz.expired:
            try:
                self._feedback(self.quiz.expire())
            except Exception as e:  # the server is out of reach: say so, and stop the clock
                self._lost(e)
        else:
            self._bar()

    # -- rendering ------------------------------------------------------------------------

    def _bar(self) -> None:
        q = self.quiz
        kind = ""
        if q.current is not None:
            kind = "select ALL that apply" if q.current.type == "multiple" else "choose one"
        left = q.seconds_left
        clock = ""
        if left is not None:
            clock = f"   {left:4.1f}s left"
        elif q.rated:
            clock = "   rated" if self.remote else "   timed"
        self.query_one("#quiz-bar", Static).update(
            Text.assemble(
                (f"question {min(q.index + 1, len(q.questions))}/{len(q.questions)}", GREEN),
                f"   score {q.correct}/{q.answered}   streak {q.streak}",
                (clock, RED if left is not None and left < 5 else GREEN),
                "   ",
                (kind, DIM),
            )
        )

    async def _render_question(self) -> None:
        q = self.quiz.current
        feedback = self.query_one("#feedback", Static)
        feedback.update("")
        feedback.remove_class("right", "wrong")
        box = self.query_one("#choices", Vertical)
        # Awaited: the next question's widget reuses the id `answer`, and mounting it while the
        # old one is still being removed raises DuplicateIds.
        await box.remove_children()
        code = self.query_one("#question-code", Static)
        if q is None:
            pct = self.quiz.percent
            self.query_one("#question", Static).update(
                Text.assemble(
                    ("Done. ", GREEN),
                    f"{self.quiz.correct} of {self.quiz.answered} right ({pct}%), "
                    f"best streak {self.quiz.best_streak}. Esc to go back.",
                )
            )
            code.display = False
            self._bar()
            return
        self.query_one("#question", Static).update(Text(q.prompt, style="bold"))
        if q.code:
            code.display = True
            code.update(
                Syntax(q.code.rstrip(), q.code_lang, theme="monokai", background_color="#0f1512")
            )
        else:
            code.display = False
        labels = [f"{i}  {c.text}" for i, c in enumerate(q.choices, start=1)]
        if q.type == "single":
            answer = RadioSet(*(RadioButton(lbl) for lbl in labels), id="answer")
        else:
            answer = SelectionList[str](
                *((lbl, c.id) for lbl, c in zip(labels, q.choices, strict=True)), id="answer"
            )
        await box.mount(answer)
        # The widget itself, not a lookup by id: by the next refresh it may already be replaced.
        self.call_after_refresh(answer.focus)
        self._bar()

    def _selected(self) -> set[str]:
        q = self.quiz.current
        assert q is not None
        widget = self.query_one("#answer")
        if isinstance(widget, RadioSet):
            i = widget.pressed_index
            return {q.choices[i].id} if i >= 0 else set()
        return set(widget.selected)

    # -- actions --------------------------------------------------------------------------

    def action_toggle(self, n: int) -> None:
        q = self.quiz.current
        if q is None or self.quiz.awaiting_next or n > len(q.choices):
            return
        widget = self.query_one("#answer")
        if isinstance(widget, RadioSet):
            list(widget.query(RadioButton))[n - 1].value = True
        else:
            widget.toggle(q.choices[n - 1].id)

    async def action_submit(self) -> None:
        if self.quiz.finished:
            return
        if self.quiz.awaiting_next:
            await self.action_next()
            return
        try:
            outcome = self.quiz.answer(self._selected())
        except ValueError as e:
            self.notify(str(e), severity="warning")
            return
        except Exception as e:  # a rated run's answer did not reach the server
            self._lost(e)
            return
        self._feedback(outcome)

    def _lost(self, error: Exception) -> None:
        self.quiz.index = len(self.quiz.questions)  # the run cannot go on; the server closes it
        self.query_one("#question", Static).update(
            Text.assemble(("The rated run stopped: ", RED), str(error), "\nEsc to go back.")
        )

    def _feedback(self, outcome) -> None:
        """Show what the answer was, and why — right, wrong, or out of time."""
        progress.record_theory(self.quiz.topic, outcome.correct, self.quiz.streak)
        q = outcome.question
        right = ", ".join(
            f"{q.choices.index(c) + 1}  {c.text}" for c in q.choices if c.id in q.answer
        )
        fb = self.query_one("#feedback", Static)
        fb.add_class("right" if outcome.correct else "wrong")
        if outcome.expired:
            headline = ("⏱ Out of time\n\n", RED)
        elif outcome.correct:
            headline = ("✓ Right\n\n", GREEN)
        else:
            headline = ("✗ Not quite\n\n", RED)
        fb.update(
            Text.assemble(
                headline,
                ("Answer: ", "bold"),
                right,
                "\n\n",
                " ".join(q.explanation.split()),
                "\n\n",
                ("See: " + " · ".join(q.references), DIM),
                ("\n\nEnter or n for the next question", DIM),
            )
        )
        self.query_one("#answer").disabled = True
        self.query_one("#quizprogress", ProgressBar).advance(1)
        self._bar()

    async def action_next(self) -> None:
        if self.quiz.awaiting_next:
            try:
                self.quiz.next()
            except Exception as e:
                self._lost(e)
                return
            await self._render_question()
            if self.quiz.finished:
                self._report()

    @work(thread=True)
    def _report(self) -> None:
        """A rated run was graded and rated on the server: say what it did. A timed run on a
        published bank is recorded on the profile, never rated. Silent when nobody is signed in."""
        if self.remote:
            result = getattr(self.quiz, "result", {}) or {}
            moves = ", ".join(
                f"{t} {d:+.0f}" for t, d in sorted((result.get("rating_delta") or {}).items())
            )
            if moves:
                self.app.call_from_thread(self.notify, f"rated {result.get('outcome')}: {moves}")
            return
        if self.reported or not self.quiz.rated or not self.quiz.answered:
            return
        self.reported = True
        from norboten import auth
        from norboten.tutor.client import ApiUnavailable, Client

        if not auth.headers():
            return
        try:
            answer = Client().record_attempt(self.quiz.attempt(self.topics))
        except ApiUnavailable:
            return
        moves = ", ".join(
            f"{t} {d:+.0f}" for t, d in sorted(answer.get("rating_delta", {}).items())
        )
        if moves:
            self.app.call_from_thread(self.notify, f"rating: {moves}")
