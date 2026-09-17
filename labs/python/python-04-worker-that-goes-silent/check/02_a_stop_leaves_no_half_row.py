import json
import os
import shutil
import tempfile
import time
from importlib.machinery import SourceFileLoader


def _probe(ctx):
    path = os.path.join(ctx.lab_dir, "files", "probe.py")
    return SourceFileLoader("ingest_probe", path).load_module()


def check(ctx):
    probe = _probe(ctx)
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        queue = os.path.join(base, "queue")
        os.makedirs(queue)
        for n in range(1, 4):
            ctx.write(os.path.join(queue, f"invoice-{n:03d}.txt"), f"{n}0.00\n")
        proc = probe.start(base, {"INGEST_WORK_SECONDS": "3"})
        time.sleep(1.5)  # in the middle of the first file
        took, out = probe.terminate(proc)
        if took is None:
            probe.kill(proc)
            return ctx.failed("The worker did not stop within five seconds of SIGTERM.")
        ledger = ctx.read(os.path.join(base, "ledger.csv"))
        state_raw = ctx.read(os.path.join(base, "done.json"))
        evidence = (
            f"SIGTERM 1.5 s into a 3 s file\nstopped after {took:.1f}s, "
            f"exit {proc.returncode}\noutput: {out!r}\n"
            f"ledger: {ledger!r}\nstate: {state_raw!r}"
        )
        if ledger:
            rows = ledger.splitlines()
            partial = [r for r in rows if len(r.split(",")) != 2 or not r.split(",")[1].strip()]
            if partial or not ledger.endswith("\n"):
                return ctx.failed("The stop left a half-written row in the ledger.", evidence)
        if state_raw is not None:
            try:
                json.loads(state_raw)
            except ValueError:
                return ctx.failed("The stop left a state file that cannot be read.", evidence)
        return ctx.passed(f"The worker stopped in {took:.1f}s with nothing half written.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
