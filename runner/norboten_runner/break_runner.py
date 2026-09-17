"""Apply a lab's faults: python3 -m norboten_runner.break_runner <lab_dir> --learner <user>

Runs every break/NN_*.py apply(ctx) in order, as root, then persists ctx.state for the checks.
Prints one JSON line: {"applied": [...]} or {"error": "...", "script": "..."}.
"""

from __future__ import annotations

import argparse
import signal
import traceback

from norboten_runner import loader
from norboten_runner.context import Context
from norboten_runner.report import emit

SCRIPT_TIMEOUT = 120


class _Timeout(Exception):
    pass


def _alarm(signum, frame):
    raise _Timeout()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("lab_dir")
    ap.add_argument("--learner", required=True)
    args = ap.parse_args(argv)

    ctx = Context(args.lab_dir, phase="break", learner=args.learner)
    signal.signal(signal.SIGALRM, _alarm)
    applied = []
    for script_id, path in loader.scripts(args.lab_dir, "break"):
        signal.alarm(SCRIPT_TIMEOUT)
        try:
            loader.load(path, script_id).apply(ctx)
        except _Timeout:
            emit({"error": f"timed out after {SCRIPT_TIMEOUT}s", "script": script_id})
            return 1
        except Exception:
            emit({"error": traceback.format_exc(limit=5), "script": script_id})
            return 1
        finally:
            signal.alarm(0)
        applied.append(script_id)
        ctx.save_state()  # persist after each script, so a later failure keeps earlier values
    emit({"applied": applied})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
