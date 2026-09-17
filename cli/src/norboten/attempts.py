"""Reporting a graded lab attempt to the API — the one place both the TUI and CI tooling use."""

from __future__ import annotations

import time

from norboten.models import GradeReport
from norboten.session.state import Session


def payload(session: Session, report: GradeReport, now: float | None = None) -> dict:
    """What the server is told. Difficulty, topics and the time limit are not in it: the server
    reads those from the manifest, so a client cannot choose its own opponent."""
    started = session.clock_started_at or session.started_at
    return {
        "lab_id": session.lab_id,
        "started_at": started,
        "duration_seconds": max(0, int((now or time.time()) - started)),
        "score_percent": report.score_percent,
        "passed": report.passed,
    }


def report(session: Session | None, graded: GradeReport) -> str | None:
    """Send a graded attempt, if anyone is signed in. Returns a line worth showing, or None.

    Never raises: a check that passed on the machine has passed, whatever the network does.
    """
    from norboten import auth
    from norboten.tutor.client import ApiUnavailable, Client

    if session is None or not graded.graded or not auth.headers():
        return None
    if session.rated:
        return None  # the server graded and recorded a rated attempt itself

    try:
        answer = Client().record_attempt(payload(session, graded))
    except ApiUnavailable as e:
        return f"the attempt was not recorded: {e}"
    deltas = answer.get("rating_delta") or {}
    if not deltas:
        return "recorded on your profile — an unrated lab never moves the rating; rated labs do"
    moves = ", ".join(f"{topic} {delta:+.0f}" for topic, delta in sorted(deltas.items()))
    return f"rating: {moves} → {answer['overall']['rating']}"
