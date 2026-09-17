"""Rated theory: questions served one at a time, answered against the server's clock
(docs/quiz-spec.md §6).

A question goes out without its answer, explanation or references; they come back only once the
answer is in. The clock is the server's own: a question is timed from the moment it was served,
with a small allowance for the network, so a slow answer is a wrong one wherever the learner sits.
"""

from __future__ import annotations

import random
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from norboten.models import Question
from norboten_api import accounts as acc
from norboten_api import live
from norboten_api.account_store import AccountStore
from norboten_api.auth import current_user, get_accounts
from norboten_api.deps import client_key, get_bus, rated_banks
from norboten_api.rated_store import RatedQuizSession, RatedStore, ServedQuestion
from norboten_api.routers.profile import settle
from norboten_api.settings import settings

router = APIRouter(prefix="/rated/quiz", tags=["rated"])

#: Questions in one rated run, at most: a bank's whole set, shuffled, when it has fewer.
RUN_LENGTH = 10
#: Seconds a served question's clock is extended by, for the round trip.
NETWORK_GRACE = 2.0
#: A run left alone this long is closed on what was answered.
EXPIRY_SECONDS = 3600
PASS_PERCENT = 70


def quiz_store(request: Request) -> RatedStore[RatedQuizSession]:
    return request.app.state.rated_quiz


class StartQuiz(BaseModel):
    topic: str


class AnswerIn(BaseModel):
    question_id: str
    selected: list[str] = Field(default_factory=list, max_length=6)


def _bank(topic: str):
    bank = rated_banks().get(topic)
    if bank is None:
        raise HTTPException(404, f"no rated bank {topic!r} on this server")
    return bank


def _question(topic: str, question_id: str) -> Question:
    return next(q for q in _bank(topic).bank.questions if q.id == question_id)


def _ask(q: Question) -> dict:
    """What a learner sees before answering — no answer, no explanation, no references."""
    return {
        "id": q.id,
        "type": q.type,
        "difficulty": q.difficulty,
        "prompt": q.prompt,
        "code": q.code,
        "code_lang": q.code_lang,
        "choices": [c.model_dump() for c in q.choices],
        "time_limit_seconds": q.time_limit_seconds,
    }


@router.get("/banks")
async def list_banks(user: acc.User = Depends(current_user)) -> list[dict]:
    """The rated question banks: topic, title, description, topics and how many questions a run
    asks. Empty on a server with no rated content."""
    return [
        {
            "topic": b.topic,
            "title": b.bank.title,
            "description": b.bank.description,
            "topics": list(b.bank.topics),
            "questions": min(RUN_LENGTH, len(b.bank.questions)),
        }
        for b in rated_banks().values()
    ]


@router.post("/sessions", status_code=201)
async def start_quiz(
    body: StartQuiz,
    request: Request,
    user: acc.User = Depends(current_user),
    accounts: AccountStore = Depends(get_accounts),
    runs: RatedStore[RatedQuizSession] = Depends(quiz_store),
    bus=Depends(get_bus),
) -> dict:
    """Start a rated run and serve its first question. A run still open for this account is closed
    first, on what it had answered — a question seen and not answered counts as wrong."""
    if await live.limited(bus, "rated-quiz", client_key(request), settings().rated_per_minute):
        raise HTTPException(429, "too many rated runs started this minute")
    bank = _bank(body.topic)
    for stale in await runs.open_for(user.user_id):
        await _close(stale, "abandoned", accounts, runs)
    ids = [q.id for q in bank.bank.questions]
    order = random.SystemRandom().sample(ids, min(RUN_LENGTH, len(ids)))
    now = time.time()
    run = RatedQuizSession(
        attempt_id=secrets.token_urlsafe(18),
        user_id=user.user_id,
        topic=bank.topic,
        issued_at=now,
        expires_at=now + EXPIRY_SECONDS,
        order=order,
        served=[ServedQuestion(id=order[0], asked_at=now)],
    )
    await runs.put(run)
    return {
        "session_id": run.attempt_id,
        "topic": bank.topic,
        "title": bank.bank.title,
        "total": len(order),
        "question": _ask(_question(bank.topic, order[0])),
    }


async def _open_run(
    session_id: str,
    user: acc.User,
    accounts: AccountStore,
    runs: RatedStore[RatedQuizSession],
) -> RatedQuizSession:
    run = await runs.get(session_id)
    if run is None or run.user_id != user.user_id:
        raise HTTPException(404, "no such run")
    if run.open and run.expires_at < time.time():
        await _close(run, "expired", accounts, runs)
        run = await runs.get(session_id)
    if run is None or not run.open:
        raise HTTPException(410, "this run is over")
    return run


@router.post("/sessions/{session_id}/answers")
async def answer(
    session_id: str,
    body: AnswerIn,
    user: acc.User = Depends(current_user),
    accounts: AccountStore = Depends(get_accounts),
    runs: RatedStore[RatedQuizSession] = Depends(quiz_store),
) -> dict:
    """Answer the question on screen. Graded here, against the time it was served: the verdict,
    the right answer, the explanation and the references. The last answer closes and rates the
    run. An empty selection is how a client reports that its clock ran out."""
    run = await _open_run(session_id, user, accounts, runs)
    current = run.served[-1]
    if current.selected is not None or current.id != body.question_id:
        raise HTTPException(409, "that is not the question on screen")
    q = _question(run.topic, current.id)
    late = time.time() > current.asked_at + q.time_limit_seconds + NETWORK_GRACE
    current.selected = sorted(set(body.selected))
    current.expired = late or not body.selected
    current.correct = not current.expired and q.is_correct(set(body.selected))
    finished = len(run.served) == len(run.order)
    out = {
        "question_id": q.id,
        "correct": current.correct,
        "expired": current.expired,
        "answer": list(q.answer),
        "explanation": q.explanation,
        "references": list(q.references),
        "answered": len(run.served),
        "right": sum(1 for s in run.served if s.correct),
        "total": len(run.order),
        "finished": finished,
    }
    if finished:
        return out | await _close(run, "", accounts, runs)
    await runs.put(run)
    return out


@router.post("/sessions/{session_id}/next")
async def next_question(
    session_id: str,
    user: acc.User = Depends(current_user),
    accounts: AccountStore = Depends(get_accounts),
    runs: RatedStore[RatedQuizSession] = Depends(quiz_store),
) -> dict:
    """Serve the next question; its clock starts now. Asked for when the learner has read the
    last explanation, so reading it costs nothing."""
    run = await _open_run(session_id, user, accounts, runs)
    if run.served[-1].selected is None:
        raise HTTPException(409, "answer the question on screen first")
    qid = run.order[len(run.served)]
    run.served.append(ServedQuestion(id=qid, asked_at=time.time()))
    await runs.put(run)
    return {"question": _ask(_question(run.topic, qid)), "index": len(run.served)}


async def _close(
    run: RatedQuizSession,
    outcome: str,
    accounts: AccountStore,
    runs: RatedStore[RatedQuizSession],
) -> dict:
    """Close a run and rate it: one game at the mean difficulty of the questions served, won at
    70%. Every question served counts, answered or not."""
    bank = rated_banks().get(run.topic)
    served = run.served
    right = sum(1 for s in served if s.correct)
    run.score_percent = right * 100 // len(served) if served else 0
    passed = run.score_percent >= PASS_PERCENT
    run.outcome = outcome or ("passed" if passed else "failed")  # type: ignore[assignment]
    run.closed_at = time.time()
    overall = None
    if bank is not None and served:
        by_id = {q.id: q for q in bank.bank.questions}
        known = [by_id[s.id].difficulty for s in served if s.id in by_id]
        run.difficulty = round(sum(known) / len(known)) if known else 1
        scored, overall = await settle(
            accounts,
            acc.Attempt(
                user_id=run.user_id,
                kind="quiz",
                lab_id=run.topic,
                started_at=run.issued_at,
                duration_seconds=max(0, int(run.closed_at - run.issued_at)),
                score_percent=run.score_percent,
                passed=run.outcome == "passed",
                rated=True,
                difficulty=run.difficulty,
                topics=list(bank.bank.topics),
            ),
        )
        run.rating_delta = scored.rating_delta
    await runs.put(run)
    return {
        "outcome": run.outcome,
        "score_percent": run.score_percent,
        "passed": run.outcome == "passed",
        "rating_delta": run.rating_delta,
    } | ({"overall": overall} if overall else {})


async def expire(
    accounts: AccountStore, runs: RatedStore[RatedQuizSession], now: float | None = None
) -> int:
    stale = await runs.expired(now or time.time())
    for run in stale:
        await _close(run, "expired", accounts, runs)
    return len(stale)
