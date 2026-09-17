"""Talking to the Norboten API: where it is, and reporting a graded attempt.

The tutor and the post-mortem do not come through here: they run on this machine
(`tutor/agent.py`, `tutor/review.py`). When the API is out of reach, every call raises
ApiUnavailable and the caller carries on offline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

DEFAULT_API = "https://api.norboten.org"


class ApiUnavailable(RuntimeError):
    pass


def base_url() -> str:
    return os.environ.get("NORBOTEN_API", DEFAULT_API).rstrip("/")


def configured() -> bool:
    return bool(os.environ.get("NORBOTEN_API"))


@dataclass
class Client:
    timeout: float = 60.0

    def record_attempt(self, payload: dict) -> dict:
        """Report a finished attempt. The server rates it; it decides the difficulty and clock."""
        from norboten import auth

        try:
            r = httpx.post(
                f"{base_url()}/attempts",
                json=payload,
                headers=auth.headers(),
                timeout=self.timeout,
            )
        except httpx.HTTPError as e:
            raise ApiUnavailable(f"the API is not reachable: {e}") from None
        if r.status_code >= 400:
            raise ApiUnavailable(f"the API answered HTTP {r.status_code}")
        return r.json()
