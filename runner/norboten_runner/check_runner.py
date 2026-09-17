"""Grade the machine: python3 -m norboten_runner.check_runner <lab_dir> --phase pre_reboot

Prints one JSON line per pass: {"phase": ..., "results": [{"id","passed","message","evidence"}]}.
With --watch N it repeats every N seconds until killed (the TUI's live panel).
"""

from __future__ import annotations

import argparse
import signal
import time
import traceback

from norboten_runner import loader
from norboten_runner.context import Context
from norboten_runner.report import emit, make_result

CHECK_TIMEOUT = 30


class _Timeout(Exception):
    pass


def _alarm(signum, frame):
    raise _Timeout()


def run_checks(lab_dir: str, phase: str, learner: str) -> list[dict]:
    ctx = Context(lab_dir, phase=phase, learner=learner)
    results = []
    for check_id, path in loader.scripts(lab_dir, "check"):
        ctx.check_id = check_id
        signal.alarm(CHECK_TIMEOUT)
        try:
            result = loader.load(path, check_id).check(ctx)
            if not isinstance(result, dict) or "passed" not in result:
                result = make_result(check_id, False, "check returned no result (lab bug)")
        except _Timeout:
            result = make_result(check_id, False, f"check timed out after {CHECK_TIMEOUT}s")
        except Exception as e:
            result = make_result(
                check_id, False, f"check crashed: {e}", traceback.format_exc(limit=4)
            )
        finally:
            signal.alarm(0)
        result["id"] = check_id
        results.append(result)
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("lab_dir")
    ap.add_argument("--phase", default="pre_reboot", choices=["live", "pre_reboot", "post_reboot"])
    ap.add_argument("--learner", required=True)
    ap.add_argument("--watch", type=float, default=0)
    args = ap.parse_args(argv)
    signal.signal(signal.SIGALRM, _alarm)

    while True:
        emit({"phase": args.phase, "results": run_checks(args.lab_dir, args.phase, args.learner)})
        if not args.watch:
            return 0
        time.sleep(args.watch)


if __name__ == "__main__":
    raise SystemExit(main())
