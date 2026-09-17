"""What the TUI shows that does not live on this machine: the account, the boards, live sessions.

Everything here is a plain synchronous call, made from a worker thread. When the API cannot be
reached the call raises `ApiUnavailable`, and the screen says so instead of hanging: the labs,
theory, journals and local recordings all work with no network at all.

`use()` swaps in another HTTP client — the tests and the site's screenshot script point the TUI at
an in-process API loaded with the sample population.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from norboten import auth
from norboten.paths import content_root
from norboten.play.session import plays_dir
from norboten.tutor.client import ApiUnavailable, base_url

_client: httpx.Client | None = None


def use(client: httpx.Client | None) -> None:
    global _client
    _client = client


def _request(method: str, path: str, *, params=None, body=None, signed=False) -> httpx.Response:
    headers = auth.headers() if signed else {}
    try:
        if _client is not None:
            return _client.request(method, path, params=params, json=body, headers=headers)
        with httpx.Client(base_url=base_url(), timeout=10) as client:
            return client.request(method, path, params=params, json=body, headers=headers)
    except httpx.HTTPError as e:
        raise ApiUnavailable(f"{base_url()} is not reachable ({type(e).__name__})") from None


def _detail(r: httpx.Response) -> str:
    try:
        detail = r.json().get("detail", "")
    except (ValueError, AttributeError):
        return ""
    return detail if isinstance(detail, str) else ""


def _json(r: httpx.Response):
    if r.status_code >= 400:
        raise ApiUnavailable(f"the API answered HTTP {r.status_code}")
    return r.json()


# -- the account -------------------------------------------------------------------------------


def signed_in() -> bool:
    return bool(auth.current() or os.environ.get("NORBOTEN_DEBUG_USER"))


def me() -> dict | None:
    """The signed-in profile; None when signed in without a nick yet (or not signed in)."""
    if not signed_in():
        return None
    r = _request("GET", "/me", signed=True)
    if r.status_code in (401, 403, 404):
        return None
    return _json(r)


class NickTaken(ValueError):
    pass


def claim(nick: str, country: str) -> dict:
    r = _request("POST", "/me", body={"nick": nick, "country": country.upper()}, signed=True)
    if r.status_code == 409:
        detail = _detail(r)
        raise NickTaken(detail if "chosen once" in detail else f"the nick {nick!r} is taken")
    if r.status_code == 422:
        raise ValueError(
            "a nick is 3–20 lowercase letters, digits, - or _; a country is two letters"
        )
    return _json(r)


def set_country(country: str) -> dict:
    """The one thing a profile can change after it is made."""
    r = _request("POST", "/me", body={"country": country.upper()}, signed=True)
    if r.status_code == 422:
        raise ValueError("a country is two letters, e.g. PL")
    return _json(r)


def identity() -> dict | None:
    """Who this account is on GitHub (`/auth/me`); None for a debug identity or when signed out."""
    if not signed_in():
        return None
    r = _request("GET", "/auth/me", signed=True)
    return _json(r) if r.status_code == 200 else None


def guess_country() -> str:
    """The server's offline guess from this machine's address, only to pre-fill a form."""
    try:
        return str(_json(_request("GET", "/geo/country")).get("country", ""))
    except (ApiUnavailable, AttributeError):
        return ""


def nick_draft(login: str) -> str:
    """A GitHub login as a nick draft: lower case, only what a nick may hold, three to twenty."""
    import re

    draft = re.sub(r"[^a-z0-9_-]+", "-", login.lower()).strip("-_")[:20].rstrip("-_")
    draft = draft.ljust(3, "0")
    return draft if re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,18}[a-z0-9]", draft) else ""


# -- public boards -----------------------------------------------------------------------------


def leaderboard(topic: str | None = None, limit: int = 100) -> list[dict]:
    params = {"limit": limit} | ({"topic": topic} if topic else {})
    return _json(_request("GET", "/leaderboard", params=params))


def profile(nick: str) -> dict:
    return _json(_request("GET", f"/profile/{nick}"))


def live(limit: int = 12) -> dict:
    return _json(_request("GET", "/play/live", params={"limit": limit}))


# -- recordings ----------------------------------------------------------------------------------


@dataclass
class Cast:
    """One recording, from wherever it came from, in the shape the player wants."""

    title: str
    source: str  # "here", "shipped" or "site"
    lab_id: str
    width: int
    height: int
    duration: float
    events: list = field(default_factory=list)  # [at, "o"|"i", data]
    commands: list[dict] = field(default_factory=list)  # {"at", "text"}
    changes: list[dict] = field(default_factory=list)  # {"command", "path", "diff"}
    ref: str = ""  # a path, or a session id for "site"

    @property
    def loaded(self) -> bool:
        return bool(self.events)


def _cast_file(path: Path) -> Cast:
    lines = path.read_text().splitlines()
    header = json.loads(lines[0]) if lines else {}
    events = [json.loads(line) for line in lines[1:] if line.strip()]
    log_path = path.with_name(path.name.removesuffix(".cast") + ".log.json")
    log = json.loads(log_path.read_text()) if log_path.exists() else {}
    return Cast(
        title=header.get("title") or path.stem,
        source="here",
        lab_id=log.get("lab_id", ""),
        width=int(header.get("width", 80)),
        height=int(header.get("height", 24)),
        duration=float(log.get("duration") or (events[-1][0] if events else 0)),
        events=events,
        commands=log.get("commands", []),
        changes=log.get("changes", []),
        ref=str(path),
    )


def local_casts() -> list[Cast]:
    """Sessions recorded on this machine, newest first."""
    directory = plays_dir()
    if not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob("*.cast"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            out.append(_cast_file(path))
        except (OSError, ValueError):
            continue
    return out


def shipped_casts() -> list[Cast]:
    """The real recordings the site ships: from the checkout, or the copy in the wheel."""
    root = content_root()
    if root is None:
        return []
    out = []
    for path in sorted((root / "site" / "streams").glob("*.json")):
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        header = raw.get("header", {})
        out.append(
            Cast(
                title=raw.get("title", path.stem),
                source="shipped",
                lab_id=raw.get("lab_id", ""),
                width=int(header.get("width", 100)),
                height=int(header.get("height", 28)),
                duration=float(raw.get("duration", 0)),
                events=raw.get("events", []),
                commands=raw.get("commands", []),
                changes=raw.get("changes", []),
                ref=str(path),
            )
        )
    return out


def site_cast(card: dict) -> Cast:
    """A session from the site: the card from /play/live, loaded in full."""
    body = _json(_request("GET", f"/play/sessions/{card['session_id']}"))
    header = body.get("header", {})
    return Cast(
        title=f"{card.get('nick', '?')} · {card.get('lab_title') or card.get('lab_id', '')}",
        source="site",
        lab_id=card.get("lab_id", ""),
        width=int(header.get("width", card.get("width", 80))),
        height=int(header.get("height", card.get("height", 24))),
        duration=float(card.get("duration", 0)),
        events=body.get("events", []),
        commands=body.get("commands", []),
        changes=body.get("changes", []),
        ref=card["session_id"],
    )
