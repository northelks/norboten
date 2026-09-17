"""A quiz run: order, answers, score and streak. No UI — the TUI and tests drive it."""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from norboten.models import Question


@dataclass
class Outcome:
    question: Question
    selected: set[str]
    correct: bool
    expired: bool = False  # the clock ran out before an answer landed


@dataclass
class QuizSession:
    """A quiz run. In `rated` mode every question is timed, and a slow answer is a wrong one —
    which is the whole point: an exam question you have to look up is a question you do not know.
    Practice is untimed and nothing about it is rated (docs/quiz-spec.md §3)."""

    topic: str
    questions: list[Question]
    index: int = 0
    answered: int = 0
    correct: int = 0
    streak: int = 0
    best_streak: int = 0
    history: list[Outcome] = field(default_factory=list)
    rated: bool = False
    started_at: float = field(default_factory=time.time)
    clock: Callable[[], float] = time.monotonic
    asked_at: float = 0.0
    _answered_current: bool = False

    @classmethod
    def start(
        cls,
        topic: str,
        questions: Sequence[Question],
        *,
        shuffle: bool = True,
        seed=None,
        rated: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> QuizSession:
        qs = list(questions)
        if shuffle:
            rng = random.Random(seed)
            rng.shuffle(qs)
            # the choices too: in the banks a right answer sits wherever its author put it
            qs = [q.shuffled(rng) for q in qs]
        session = cls(topic=topic, questions=qs, rated=rated, clock=clock)
        session.ask()
        return session

    # -- the clock -------------------------------------------------------------------------

    def ask(self) -> None:
        """Start the clock for the question now on screen."""
        self.asked_at = self.clock()

    @property
    def limit(self) -> int | None:
        """Seconds allowed for the current question, or None when this run is not rated."""
        q = self.current
        return q.time_limit_seconds if (self.rated and q is not None) else None

    @property
    def seconds_left(self) -> float | None:
        limit = self.limit
        if limit is None or self._answered_current:
            return None
        return max(0.0, limit - (self.clock() - self.asked_at))

    @property
    def expired(self) -> bool:
        left = self.seconds_left
        return left is not None and left <= 0

    def expire(self) -> Outcome:
        """The clock ran out: record it as wrong, with nothing selected."""
        q = self.current
        if q is None:
            raise IndexError("the quiz is over")
        if self._answered_current:
            raise RuntimeError("this question was already answered")
        return self._record(q, set(), correct=False, expired=True)

    @property
    def current(self) -> Question | None:
        return self.questions[self.index] if self.index < len(self.questions) else None

    @property
    def finished(self) -> bool:
        return self.current is None

    @property
    def awaiting_next(self) -> bool:
        return self._answered_current

    def answer(self, selected: set[str]) -> Outcome:
        q = self.current
        if q is None:
            raise IndexError("the quiz is over")
        if self._answered_current:
            raise RuntimeError("this question was already answered")
        if not selected:
            raise ValueError("select at least one choice")
        if q.type == "single" and len(selected) != 1:
            raise ValueError("choose exactly one answer")
        # A rated answer that arrives after the limit counts as wrong, however right it is.
        late = self.rated and self.expired
        return self._record(
            q, set(selected), correct=q.is_correct(selected) and not late, expired=late
        )

    def _record(
        self, q: Question, selected: set[str], *, correct: bool, expired: bool = False
    ) -> Outcome:
        self.answered += 1
        self.correct += correct
        self.streak = self.streak + 1 if correct else 0
        self.best_streak = max(self.best_streak, self.streak)
        outcome = Outcome(q, selected, correct, expired)
        self.history.append(outcome)
        self._answered_current = True
        return outcome

    def next(self) -> Question | None:
        self.index += 1
        self._answered_current = False
        self.ask()
        return self.current

    # -- what the API is told about a rated run --------------------------------------------

    @property
    def difficulty(self) -> int:
        """The run's difficulty: the mean of the questions actually answered."""
        seen = [o.question.difficulty for o in self.history]
        return round(sum(seen) / len(seen)) if seen else 1

    def attempt(self, topics: Sequence[str], *, passed_percent: int = 70) -> dict:
        """The body for POST /attempts. A quiz passes on the same line an exam does."""
        return {
            "lab_id": self.topic,
            "kind": "quiz",
            "started_at": self.started_at,
            "duration_seconds": max(0, int(time.time() - self.started_at)),
            "score_percent": self.percent,
            "passed": self.percent >= passed_percent,
            "rated": self.rated,
            "difficulty": self.difficulty,
            "topics": list(topics),
        }

    @property
    def percent(self) -> int:
        return (self.correct * 100) // self.answered if self.answered else 0
