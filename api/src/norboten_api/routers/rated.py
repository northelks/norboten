"""Rated labs: issued for one attempt, judged here, never answered (docs/lab-spec.md §13).

Every endpoint needs a token and a profile. None of them returns a criterion, a judge's message, a
hint or a solution: a learner is told which checks passed, and the rating that follows.
"""

from __future__ import annotations

import base64
import io
import secrets
import tarfile
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from norboten.labs.manifest import Lab
from norboten.models import PassResult, Phase
from norboten.session import grading
from norboten_api import accounts as acc
from norboten_api import live
from norboten_api.account_store import AccountStore
from norboten_api.auth import current_user, get_accounts
from norboten_api.deps import client_key, get_bus, rated_catalogue, rated_lab_or_none
from norboten_api.rated_store import CheckVerdict, RatedAttempt, RatedStore, Received
from norboten_api.routers.profile import settle
from norboten_api.settings import settings
from norboten_runner import signing
from norboten_runner.judge import judge_record

router = APIRouter(prefix="/rated", tags=["rated"])

#: An attempt left unfinished this many times its clock expires as a loss; never sooner than this.
EXPIRY_FACTOR = 3
MIN_EXPIRY_SECONDS = 3600
#: A record larger than this is refused before it is parsed any further.
RECORD_LIMIT = 1024 * 1024


def rated_store(request: Request) -> RatedStore:
    return request.app.state.rated


class StartIn(BaseModel):
    lab_id: str
    image: str | None = None


class FactsIn(BaseModel):
    record: dict
    signature: str = Field(min_length=64, max_length=64)


# -- the catalogue ----------------------------------------------------------------------------


def _summary(lab: Lab) -> dict:
    m = lab.manifest
    return {
        "id": m.id,
        "short_id": m.short_id,
        "title": m.title,
        "track": m.track.value,
        "topics": list(m.topics),
        "difficulty": m.difficulty,
        "estimated_minutes": m.estimated_minutes,
        "rated_minutes": m.rated_minutes,
        "base_images": m.base_images,
        "runtime": m.runtime,
        "version": m.version,
    }


@router.get("/labs")
async def list_rated(user: acc.User = Depends(current_user)) -> list[dict]:
    """The rated labs this server grades: id, title, track, topics, difficulty, clock and images.
    Nothing about what is broken. Empty on a server with no rated content."""
    return [_summary(lab) for lab in rated_catalogue().values()]


@router.get("/labs/{lab_id}")
async def read_rated_lab(lab_id: str, user: acc.User = Depends(current_user)) -> dict:
    """One rated lab's manifest and briefing — what a learner reads before starting. The faults,
    the collectors, the judges, the hints and the solution are not in it."""
    lab = _lab(lab_id)
    return {"manifest": lab.manifest.model_dump(mode="json"), "briefing": lab.briefing}


def _lab(lab_id: str) -> Lab:
    lab = rated_lab_or_none(lab_id)
    if lab is None:
        raise HTTPException(404, f"no rated lab {lab_id!r} on this server")
    return lab


def bundle(lab: Lab, part: str) -> str:
    """lab.yaml, one of break/ or collect/, and files/ — base64 of a tar.gz, entries under lab/."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(lab.path / "lab.yaml", arcname="lab/lab.yaml")
        for name in (part, "files"):
            src: Path = lab.path / name
            if src.is_dir():
                tar.add(src, arcname=f"lab/{name}", filter=_plain)
    return base64.b64encode(buf.getvalue()).decode()


def _plain(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if "__pycache__" in info.name or not (info.isfile() or info.isdir()):
        return None
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


# -- an attempt -------------------------------------------------------------------------------


@router.post("/attempts", status_code=201)
async def start(
    body: StartIn,
    request: Request,
    user: acc.User = Depends(current_user),
    accounts: AccountStore = Depends(get_accounts),
    rated: RatedStore = Depends(rated_store),
    bus=Depends(get_bus),
) -> dict:
    """Start a rated attempt: an id, a nonce, the key that signs this attempt's records, the clock,
    and the break bundle. Any attempt still open for this account is closed as a loss first —
    seeing the faults and walking away is not free."""
    if await live.limited(bus, "rated", client_key(request), settings().rated_per_minute):
        raise HTTPException(429, "too many rated attempts started this minute")
    lab = _lab(body.lab_id)
    m = lab.manifest
    image = body.image or m.base_images[0]
    if image not in m.base_images:
        raise HTTPException(422, f"{m.short_id} does not run on {image}")
    for stale in await rated.open_for(user.user_id):
        await _close(stale, "abandoned", accounts, rated)

    now = time.time()
    attempt = RatedAttempt(
        attempt_id=secrets.token_urlsafe(18),
        user_id=user.user_id,
        lab_id=m.id,
        lab_version=m.version,
        image=image,
        nonce=secrets.token_urlsafe(18),
        key=secrets.token_hex(32),
        issued_at=now,
        expires_at=now + max(MIN_EXPIRY_SECONDS, EXPIRY_FACTOR * m.rated_minutes * 60),
    )
    await rated.put(attempt)
    return {
        "attempt_id": attempt.attempt_id,
        "nonce": attempt.nonce,
        "key": attempt.key,
        "lab_id": m.id,
        "image": image,
        "issued_at": attempt.issued_at,
        "expires_at": attempt.expires_at,
        "time_limit_minutes": m.rated_minutes,
        "reboot_required": m.reboot_required,
        "bundle": bundle(lab, "break"),
    }


async def _mine(attempt_id: str, user: acc.User, rated: RatedStore) -> RatedAttempt:
    attempt = await rated.get(attempt_id)
    if attempt is None or attempt.user_id != user.user_id:
        raise HTTPException(404, "no such attempt")
    return attempt


async def _open(
    attempt_id: str, user: acc.User, accounts: AccountStore, rated: RatedStore
) -> RatedAttempt:
    attempt = await _mine(attempt_id, user, rated)
    if attempt.open and attempt.expires_at < time.time():
        await _close(attempt, "expired", accounts, rated)
        attempt = await _mine(attempt_id, user, rated)
    if not attempt.open:
        raise HTTPException(410, f"this attempt is over ({attempt.outcome})")
    return attempt


@router.get("/attempts/{attempt_id}")
async def read_attempt(
    attempt_id: str,
    user: acc.User = Depends(current_user),
    accounts: AccountStore = Depends(get_accounts),
    rated: RatedStore = Depends(rated_store),
) -> dict:
    """Where an attempt stands: open, or its outcome with each check's verdict and the rating
    change."""
    attempt = await _mine(attempt_id, user, rated)
    if attempt.open and attempt.expires_at < time.time():
        await _close(attempt, "expired", accounts, rated)
        attempt = await _mine(attempt_id, user, rated)
    return _view(attempt)


@router.get("/attempts/{attempt_id}/collect")
async def collect_bundle(
    attempt_id: str,
    user: acc.User = Depends(current_user),
    accounts: AccountStore = Depends(get_accounts),
    rated: RatedStore = Depends(rated_store),
) -> dict:
    """The collect bundle for an open attempt: which facts to gather, never what they must be."""
    attempt = await _open(attempt_id, user, accounts, rated)
    return {"bundle": bundle(_lab(attempt.lab_id), "collect")}


@router.post("/attempts/{attempt_id}/abandon")
async def abandon(
    attempt_id: str,
    user: acc.User = Depends(current_user),
    accounts: AccountStore = Depends(get_accounts),
    rated: RatedStore = Depends(rated_store),
) -> dict:
    """Give an attempt up. It is rated as a loss, like running out of time."""
    attempt = await _open(attempt_id, user, accounts, rated)
    return await _close(attempt, "abandoned", accounts, rated)


@router.post("/attempts/{attempt_id}/facts")
async def facts(
    attempt_id: str,
    body: FactsIn,
    user: acc.User = Depends(current_user),
    accounts: AccountStore = Depends(get_accounts),
    rated: RatedStore = Depends(rated_store),
) -> dict:
    """A signed fact record from the guest, before or after the reboot. The last one the lab
    needs closes the attempt: judged here, rated, and answered pass or fail per check."""
    attempt = await _open(attempt_id, user, accounts, rated)
    lab = _lab(attempt.lab_id)
    m = lab.manifest
    record = body.record
    if len(signing.canonical(record)) > RECORD_LIMIT:
        raise HTTPException(413, "the record is larger than any lab's facts can be")
    if not signing.verify(attempt.key, record, body.signature):
        raise HTTPException(403, "the record's signature does not verify for this attempt")
    if record.get("attempt") != attempt.attempt_id or record.get("nonce") != attempt.nonce:
        raise HTTPException(403, "the record belongs to another attempt")

    phases = [Phase.PRE_REBOOT.value] + ([Phase.POST_REBOOT.value] if m.reboot_required else [])
    phase = record.get("phase")
    expected = phases[len(attempt.records)]
    if phase in attempt.records:
        raise HTTPException(409, f"the {phase} record was already received")
    if phase != expected:
        raise HTTPException(409, f"the next record must be {expected}")
    if phase == Phase.POST_REBOOT.value:
        before = attempt.records[Phase.PRE_REBOOT.value].record
        if not record.get("boot_id") or record.get("boot_id") == before.get("boot_id"):
            raise HTTPException(422, "the machine was not rebooted between the two records")
        if float(record.get("collected_at") or 0) <= float(before.get("collected_at") or 0):
            raise HTTPException(422, "the second record was collected before the first")

    attempt.records[phase] = Received(record=record, received_at=time.time())
    if len(attempt.records) < len(phases):
        await rated.put(attempt)
        return {"attempt_id": attempt.attempt_id, "accepted": phase, "next": phases[-1]}
    return await _judge_and_close(attempt, lab, accounts, rated)


async def _judge_and_close(
    attempt: RatedAttempt, lab: Lab, accounts: AccountStore, rated: RatedStore
) -> dict:
    m = lab.manifest
    passes = [
        PassResult.model_validate(
            {"phase": phase, "results": judge_record(str(lab.path), received.record)}
        )
        for phase, received in attempt.records.items()
    ]
    report = grading.grade(m, attempt.image, passes)
    outcome = grading.check_outcomes(m, passes)
    first = attempt.records[Phase.PRE_REBOOT.value].received_at
    attempt.duration_seconds = max(0, int(first - attempt.issued_at))
    attempt.within_limit = attempt.duration_seconds <= m.rated_minutes * 60
    attempt.score_percent = report.score_percent
    attempt.checks = [
        CheckVerdict(id=c.id, objective=c.objective, passed=outcome[c.id]) for c in m.checks
    ]
    return await _close(attempt, "passed" if report.passed else "failed", accounts, rated, lab=lab)


async def _close(
    attempt: RatedAttempt,
    outcome: str,
    accounts: AccountStore,
    rated: RatedStore,
    lab: Lab | None = None,
) -> dict:
    """Close an attempt and rate it: a pass inside the clock wins, anything else loses."""
    lab = lab or rated_lab_or_none(attempt.lab_id)
    attempt.outcome = outcome  # type: ignore[assignment]
    attempt.closed_at = time.time()
    if outcome in ("abandoned", "expired"):
        attempt.duration_seconds = max(0, int(attempt.closed_at - attempt.issued_at))
    overall = None
    if lab is not None:
        m = lab.manifest
        scored, overall = await settle(
            accounts,
            acc.Attempt(
                user_id=attempt.user_id,
                kind="lab",
                lab_id=m.id,
                started_at=attempt.issued_at,
                duration_seconds=attempt.duration_seconds,
                score_percent=attempt.score_percent,
                passed=outcome == "passed",
                rated=True,
                within_limit=attempt.within_limit,
                difficulty=m.difficulty,
                topics=list(m.topics),
            ),
        )
        attempt.rating_delta = scored.rating_delta
    await rated.put(attempt)
    return _view(attempt) | ({"overall": overall} if overall else {})


def _view(attempt: RatedAttempt) -> dict:
    out: dict = {
        "attempt_id": attempt.attempt_id,
        "lab_id": attempt.lab_id,
        "image": attempt.image,
        "issued_at": attempt.issued_at,
        "expires_at": attempt.expires_at,
        "received": list(attempt.records),
        "outcome": attempt.outcome or "open",
    }
    if not attempt.open:
        out |= {
            "passed": attempt.outcome == "passed",
            "score_percent": attempt.score_percent,
            "within_limit": attempt.within_limit,
            "duration_seconds": attempt.duration_seconds,
            "checks": [c.model_dump() for c in attempt.checks],
            "rating_delta": attempt.rating_delta,
        }
    return out


async def expire(accounts: AccountStore, rated: RatedStore, now: float | None = None) -> int:
    """Close every attempt past its expiry as a loss. The hourly sweep calls this."""
    stale = await rated.expired(now or time.time())
    for attempt in stale:
        await _close(attempt, "expired", accounts, rated)
    return len(stale)
