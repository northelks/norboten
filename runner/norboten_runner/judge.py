"""Judge a rated lab's fact record: the half of a check that never reaches the guest.

Runs on the server, and on the host during the gate — never in a lab VM, although it is standard
library only like the rest of this package so that both can import it (docs/lab-spec.md
section 13). A judge is a pure function of the facts: `judge(facts, ctx)`.
"""

from __future__ import annotations

import traceback

from norboten_runner import loader
from norboten_runner.report import make_result


class JudgeContext:
    def __init__(self, record: dict, check_id: str = "") -> None:
        self.phase = record.get("phase", "")
        self.base = record.get("base") or {}
        self.state = record.get("state") or {}
        self.check_id = check_id

    def passed(self, message: str, evidence: str = "") -> dict:
        return make_result(self.check_id, True, message, evidence)

    def failed(self, message: str, evidence: str = "") -> dict:
        return make_result(self.check_id, False, message, evidence)


def judge_record(lab_dir: str, record: dict) -> list[dict]:
    """One result per check/NN_*.py, in file order, shaped like the check runner's."""
    facts = record.get("facts") or {}
    results = []
    for check_id, path in loader.scripts(lab_dir, "check"):
        ctx = JudgeContext(record, check_id)
        observed = facts.get(check_id)
        if not isinstance(observed, dict):
            result = ctx.failed("no facts were collected for this check")
        elif "collect_error" in observed:
            result = ctx.failed("collecting the facts failed", str(observed["collect_error"]))
        else:
            try:
                result = loader.load(path, f"judge_{check_id}").judge(observed, ctx)
                if not isinstance(result, dict) or "passed" not in result:
                    result = ctx.failed("judge returned no result (lab bug)")
            except Exception as e:
                result = ctx.failed(f"judge crashed: {e}", traceback.format_exc(limit=4))
        result["id"] = check_id
        results.append(result)
    return results
