"""Collect a rated lab's facts: python3 -m norboten_runner.collect_runner <lab_dir> --phase P
    --learner U --attempt A --nonce N  (the attempt key on stdin)

Runs every collect/NN_*.py collect(ctx) and prints one JSON line, {"record": …, "signature": …}.
The record holds what the machine looked like, never a verdict: the criteria are not here
(docs/lab-spec.md section 13).
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
import traceback

from norboten_runner import loader, signing
from norboten_runner.context import Context
from norboten_runner.report import emit

COLLECT_TIMEOUT = 30
FACTS_LIMIT = 64 * 1024
BOOT_ID = "/proc/sys/kernel/random/boot_id"


class _Timeout(Exception):
    pass


def _alarm(signum, frame):
    raise _Timeout()


def _error(message: str) -> dict:
    return {"collect_error": message}


def collect_facts(lab_dir: str, phase: str, learner: str) -> tuple[Context, dict]:
    ctx = Context(lab_dir, phase=phase, learner=learner)
    facts: dict = {}
    for check_id, path in loader.scripts(lab_dir, "collect"):
        ctx.check_id = check_id
        signal.alarm(COLLECT_TIMEOUT)
        try:
            value = loader.load(path, f"collect_{check_id}").collect(ctx)
        except _Timeout:
            value = _error(f"collector timed out after {COLLECT_TIMEOUT}s")
        except Exception:
            value = _error(traceback.format_exc(limit=4))
        finally:
            signal.alarm(0)
        if not isinstance(value, dict):
            value = _error("collector returned no JSON object (lab bug)")
        try:
            size = len(json.dumps(value))
        except (TypeError, ValueError):
            value, size = _error("collector returned something JSON cannot carry (lab bug)"), 0
        if size > FACTS_LIMIT:
            value = _error(f"collector returned {size} bytes; the limit is {FACTS_LIMIT}")
        facts[check_id] = value
    return ctx, facts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("lab_dir")
    ap.add_argument("--phase", required=True, choices=["live", "pre_reboot", "post_reboot"])
    ap.add_argument("--learner", required=True)
    ap.add_argument("--attempt", required=True)
    ap.add_argument("--nonce", required=True)
    args = ap.parse_args(argv)
    key = sys.stdin.readline().strip()  # never on the command line, where ps would show it
    signal.signal(signal.SIGALRM, _alarm)

    ctx, facts = collect_facts(args.lab_dir, args.phase, args.learner)
    record = {
        "attempt": args.attempt,
        "nonce": args.nonce,
        "phase": args.phase,
        "boot_id": (ctx.read(BOOT_ID) or "").strip(),
        "collected_at": time.time(),
        "base": ctx.facts,
        "state": ctx.state,
        "facts": facts,
    }
    emit({"record": record, "signature": signing.sign(key, record)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
