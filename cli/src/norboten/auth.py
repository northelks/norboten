"""Signing in from the terminal (`a` in the TUI): with GitHub, through its device flow.

`start` asks the Norboten server to begin a sign-in; the terminal shows the code GitHub issued and
the page to type it on (github.com/login/device), which works from any device — a headless box signs
in the same way. `poll` asks the server whether GitHub has been told yes. The server holds GitHub's
device code and talks to GitHub itself: no GitHub token ever reaches this machine, only a `cli`
token of Norboten's, labelled with this machine's name.

"Remember this machine" is the only choice. Remembered, the token is written to
~/.norboten/credentials.json with mode 0600 and lives ninety days; not remembered, it lives twelve
hours and only in this process — nothing touches the disk, and quitting norboten signs you out.
Signing out deletes it either way and asks the server to forget it.
"""

from __future__ import annotations

import contextlib
import json
import os
import platform
import time
from dataclasses import asdict, dataclass

import httpx

from norboten.paths import norboten_home
from norboten.tutor.client import ApiUnavailable, base_url


class LoginError(RuntimeError):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Credentials:
    access_token: str
    expires_at: float
    api: str = ""

    @property
    def expired(self) -> bool:
        return time.time() >= self.expires_at


def credentials_path():
    return norboten_home() / "credentials.json"


def load() -> Credentials | None:
    path = credentials_path()
    if not path.exists():
        return None
    try:
        return Credentials(**json.loads(path.read_text()))
    except (OSError, ValueError, TypeError):
        return None


def save(creds: Credentials) -> None:
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=True)
    path.chmod(0o600)
    path.write_text(json.dumps(asdict(creds), indent=2) + "\n")


#: A token that was not to be remembered: this process's only copy, never written down.
_session: Credentials | None = None


def current() -> Credentials | None:
    """Who is signed in on this machine: this process's session first, then the stored file."""
    if _session is not None and not _session.expired:
        return _session
    return load()


def forget() -> bool:
    """Sign out here, and tell the server to revoke the token (best effort)."""
    global _session
    creds = current()
    path = credentials_path()
    if creds is None and not path.exists():
        return False
    if creds is not None:
        with contextlib.suppress(httpx.HTTPError):  # offline: the token still expires anyway
            httpx.post(
                f"{base_url()}/auth/logout",
                headers={"Authorization": f"Bearer {creds.access_token}"},
                timeout=10,
            )
    _session = None
    path.unlink(missing_ok=True)
    return True


def _post(path: str, payload: dict) -> httpx.Response:
    try:
        return httpx.post(f"{base_url()}{path}", json=payload, timeout=15)
    except httpx.HTTPError as e:
        raise ApiUnavailable(f"cannot reach {base_url()}: {e}") from None


def _detail(r: httpx.Response, fallback: str) -> str:
    try:
        detail = r.json().get("detail")
    except ValueError:
        return fallback
    return detail if isinstance(detail, str) and detail else fallback


def label() -> str:
    """How this machine is named in the account's list of signed-in terminals."""
    return f"{platform.node() or 'a terminal'} ({platform.system()})"[:120]


@dataclass(frozen=True)
class DeviceStart:
    poll_id: str
    user_code: str
    verification_uri: str
    interval: int
    expires_in: int


@dataclass(frozen=True)
class Waiting:
    """GitHub has not been told yet; ask again in `interval` seconds."""

    interval: int


def start(remember: bool) -> DeviceStart:
    """Begin signing this machine in. Raises `LoginError` when the server cannot."""
    r = _post("/auth/github/device", {"label": label(), "remember": remember})
    if r.status_code == 503:
        raise LoginError("sign-in is not configured on this server", 503)
    if r.status_code != 200:
        raise LoginError(_detail(r, f"the server would not start a sign-in (HTTP {r.status_code})"))
    body = r.json()
    return DeviceStart(
        poll_id=body["poll_id"],
        user_code=body["user_code"],
        verification_uri=body["verification_uri"],
        interval=int(body.get("interval", 5)),
        expires_in=int(body.get("expires_in", 900)),
    )


def poll(poll_id: str, remember: bool) -> Credentials | Waiting:
    """One question to the server: signed in yet? `Waiting` while GitHub waits (and says how long to
    wait, longer after a slow-down); `Credentials` once approved; `LoginError` when it is over —
    403 denied on GitHub, 410 expired or already used."""
    global _session
    r = _post("/auth/github/poll", {"poll_id": poll_id, "remember": remember})
    if r.status_code in (428, 429):
        try:
            interval = int(r.json().get("interval", 5))
        except (ValueError, AttributeError):
            interval = 5
        return Waiting(interval)
    if r.status_code != 200:
        raise LoginError(_detail(r, f"sign-in failed (HTTP {r.status_code})"), r.status_code)
    body = r.json()
    creds = Credentials(
        access_token=body["access_token"],
        expires_at=time.time() + float(body.get("expires_in", 0)),
        api=base_url(),
    )
    if remember:
        save(creds)
        _session = None
    else:
        credentials_path().unlink(missing_ok=True)  # a stale remembered token must not win later
        _session = creds
    return creds


def token() -> str | None:
    """A usable token, or None when nobody is signed in on this machine."""
    creds = current()
    if creds is None or creds.expired:
        return None
    return creds.access_token


def headers() -> dict[str, str]:
    """Authorization for an API call, or the debug identity when one is set for local work."""
    bearer = token()
    if bearer:
        return {"Authorization": f"Bearer {bearer}"}
    debug = os.environ.get("NORBOTEN_DEBUG_USER", "")
    return {"X-Debug-User": debug} if debug else {}
