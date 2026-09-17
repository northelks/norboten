"""A rated theory run whose questions and grading live on the server (docs/quiz-spec.md §6).

It answers to the same calls as `QuizSession`, so the quiz screen drives either. What differs is
where the truth is: a question arrives without its answer, the server's clock is the one that
counts, and the explanation comes back with the verdict. The local clock only draws the countdown;
when it runs out the run reports an empty answer, which the server records as out of time.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from norboten import rated
from norboten.models import Question
from norboten.quiz.session import Outcome

_WAITING = "The answer, and why, comes back from the server once you have answered."


def _placeholder(served: dict) -> Question:
    """A served question as the screen's model; its answer is unknown here until it is graded."""
    return Question.model_validate(
        {
            k: served[k]
            for k in ("id", "type", "difficulty", "prompt", "code", "code_lang", "choices")
        }
        | {"answer": [served["choices"][0]["id"]], "explanation": _WAITING, "references": ["—"]}
    )


@dataclass
class RemoteQuiz:
    session_id: str
    topic: str
    total: int
    served: dict
    index: int = 0
    answered: int = 0
    correct: int = 0
    streak: int = 0
    best_streak: int = 0
    history: list[Outcome] = field(default_factory=list)
    rated: bool = True
    started_at: float = field(default_factory=time.time)
    clock: Callable[[], float] = time.monotonic
    asked_at: float = 0.0
    result: dict = field(default_factory=dict)  # the closing verdict, once the last answer is in
    _answered_current: bool = False

    @classmethod
    def start(cls, topic: str, clock: Callable[[], float] = time.monotonic) -> RemoteQuiz:
        started = rated.start_quiz(topic)
        quiz = cls(
            session_id=started["session_id"],
            topic=topic,
            total=started["total"],
            served=started["question"],
            clock=clock,
        )
        quiz.asked_at = clock()
        return quiz

    # -- what the screen reads ------------------------------------------------------------

    @property
    def questions(self) -> list[None]:
        return [None] * self.total

    @property
    def current(self) -> Question | None:
        return None if self.finished else _placeholder(self.served)

    @property
    def finished(self) -> bool:
        return self.index >= self.total

    @property
    def awaiting_next(self) -> bool:
        return self._answered_current

    @property
    def limit(self) -> int | None:
        return None if self.finished else int(self.served["time_limit_seconds"])

    @property
    def seconds_left(self) -> float | None:
        if self.finished or self._answered_current:
            return None
        return max(0.0, self.served["time_limit_seconds"] - (self.clock() - self.asked_at))

    @property
    def expired(self) -> bool:
        left = self.seconds_left
        return left is not None and left <= 0

    @property
    def percent(self) -> int:
        return (self.correct * 100) // self.answered if self.answered else 0

    # -- what the screen does -------------------------------------------------------------

    def answer(self, selected: set[str]) -> Outcome:
        if self.finished or self._answered_current:
            raise RuntimeError("this question was already answered")
        if not selected:
            raise ValueError("select at least one choice")
        if self.served["type"] == "single" and len(selected) != 1:
            raise ValueError("choose exactly one answer")
        return self._send(set(selected))

    def expire(self) -> Outcome:
        if self.finished or self._answered_current:
            raise RuntimeError("this question was already answered")
        return self._send(set())

    def _send(self, selected: set[str]) -> Outcome:
        graded = rated.answer_question(self.session_id, self.served["id"], sorted(selected))
        question = _placeholder(self.served).model_copy(
            update={
                "answer": graded["answer"],
                "explanation": graded["explanation"],
                "references": graded["references"],
            }
        )
        correct = bool(graded["correct"])
        self.answered += 1
        self.correct += correct
        self.streak = self.streak + 1 if correct else 0
        self.best_streak = max(self.best_streak, self.streak)
        outcome = Outcome(question, selected, correct, bool(graded["expired"]))
        self.history.append(outcome)
        self._answered_current = True
        if graded.get("finished"):
            self.result = graded
        return outcome

    def next(self) -> Question | None:
        self.index += 1
        self._answered_current = False
        if not self.finished:
            self.served = rated.next_question(self.session_id)["question"]
            self.asked_at = self.clock()
        return self.current
