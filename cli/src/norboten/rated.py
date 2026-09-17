"""The client half of a rated lab (docs/lab-spec.md §13): the catalogue, and one attempt's calls.

What this machine keeps of a rated lab is what the server publishes about it anyway — the manifest
and the briefing, in ~/.norboten/rated/<id>/, so the Labs section can list them offline. The break
and collect bundles are fetched when they are needed and injected straight into the guest; the
judges, the hints and the solution never leave the server.

Calls go through `norboten.tui.data`, so the tests and the site's screenshot script can point them
at an in-process API exactly as they do for the rest of the TUI.
"""

from __future__ import annotations

import base64
import shutil
from pathlib import Path

import yaml

from norboten.labs.manifest import Lab, LabError
from norboten.paths import norboten_home
from norboten.tutor.client import ApiUnavailable


class RatedError(RuntimeError):
    """The server refused (the message is its own), or there is no server or no sign-in."""


def home() -> Path:
    return norboten_home() / "rated"


def _call(method: str, path: str, body: dict | None = None) -> dict | list:
    from norboten.tui import data

    if not data.signed_in():
        raise RatedError("a rated lab is graded on the server: sign in first (a)")
    try:
        r = data._request(method, path, body=body, signed=True)
    except ApiUnavailable as e:
        raise RatedError(f"a rated lab needs the server, and it is out of reach: {e}") from None
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = None
        raise RatedError(detail or f"the API answered HTTP {r.status_code}")
    return r.json()


# -- the catalogue ----------------------------------------------------------------------------


def cached_labs() -> list[Lab]:
    """The rated labs last fetched from the server. Nothing offline beyond their briefings."""
    root = home()
    labs = []
    for path in sorted(root.glob("*/lab.yaml")) if root.is_dir() else []:
        try:
            lab = Lab.load(path.parent)
        except LabError:
            continue  # an image this version does not know; the next refresh replaces it
        if lab.manifest.rated:
            labs.append(lab)
    return labs


def refresh() -> list[Lab]:
    """Fetch the rated catalogue: each lab's manifest and briefing, written to the cache. A lab the
    server no longer lists is removed from it."""
    listed = _call("GET", "/rated/labs")
    root = home()
    root.mkdir(parents=True, exist_ok=True)
    keep = set()
    for summary in listed:
        lab_id = summary["id"]
        one = _call("GET", f"/rated/labs/{lab_id}")
        target = root / lab_id
        target.mkdir(exist_ok=True)
        (target / "lab.yaml").write_text(yaml.safe_dump(one["manifest"], sort_keys=False))
        (target / "briefing.md").write_text(one["briefing"])
        keep.add(lab_id)
    for stale in root.iterdir():
        if stale.is_dir() and stale.name not in keep:
            shutil.rmtree(stale)
    return cached_labs()


# -- one attempt ------------------------------------------------------------------------------


def start(lab_id: str, image: str) -> dict:
    return _call("POST", "/rated/attempts", {"lab_id": lab_id, "image": image})


def attempt(attempt_id: str) -> dict:
    return _call("GET", f"/rated/attempts/{attempt_id}")


def collect_bundle(attempt_id: str) -> bytes:
    return base64.b64decode(_call("GET", f"/rated/attempts/{attempt_id}/collect")["bundle"])


def send_facts(attempt_id: str, collected: dict) -> dict:
    return _call("POST", f"/rated/attempts/{attempt_id}/facts", collected)


def abandon(attempt_id: str) -> dict:
    return _call("POST", f"/rated/attempts/{attempt_id}/abandon")


# -- rated theory (docs/quiz-spec.md §6) ------------------------------------------------------


def _banks_file() -> Path:
    return home() / "banks.json"


def cached_banks() -> list[dict]:
    """The rated banks last listed by the server: topic, title, description, topics, length."""
    import json

    try:
        return json.loads(_banks_file().read_text())
    except (OSError, ValueError):
        return []


def refresh_banks() -> list[dict]:
    import json

    banks = _call("GET", "/rated/quiz/banks")
    home().mkdir(parents=True, exist_ok=True)
    _banks_file().write_text(json.dumps(banks, indent=2))
    return banks


def start_quiz(topic: str) -> dict:
    return _call("POST", "/rated/quiz/sessions", {"topic": topic})


def answer_question(session_id: str, question_id: str, selected: list[str]) -> dict:
    body = {"question_id": question_id, "selected": selected}
    return _call("POST", f"/rated/quiz/sessions/{session_id}/answers", body)


def next_question(session_id: str) -> dict:
    return _call("POST", f"/rated/quiz/sessions/{session_id}/next")
