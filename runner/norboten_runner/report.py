"""Result shapes the runner prints. The CLI parses them into norboten.models.CheckResult."""

from __future__ import annotations

import json
import sys

EVIDENCE_LIMIT = 4096


def truncate(text: str, limit: int = EVIDENCE_LIMIT) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return "…" + text[-(limit - 1) :]


def make_result(check_id: str, passed: bool, message: str, evidence: str = "") -> dict:
    return {
        "id": check_id,
        "passed": bool(passed),
        "message": str(message),
        "evidence": truncate(str(evidence)),
    }


def emit(obj: dict) -> None:
    """One JSON document per line on stdout — the only channel back to the host."""
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()
