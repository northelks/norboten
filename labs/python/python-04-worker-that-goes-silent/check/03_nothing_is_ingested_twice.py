import os
import re
import shutil
import tempfile
import time
from importlib.machinery import SourceFileLoader

FILES = 3


def _probe(ctx):
    path = os.path.join(ctx.lab_dir, "files", "probe.py")
    return SourceFileLoader("ingest_probe", path).load_module()


def _names(text):
    """Every mention of a queue file in the ledger — a second one means a second ingest, even when
    a half-written row ran into the row that followed it."""
    return re.findall(r"invoice-\d{3}\.txt", text or "")


def check(ctx):
    probe = _probe(ctx)
    base = tempfile.mkdtemp(prefix=".norboten-probe-")
    try:
        queue = os.path.join(base, "queue")
        os.makedirs(queue)
        for n in range(1, FILES + 1):
            ctx.write(os.path.join(queue, f"invoice-{n:03d}.txt"), f"{n}0.00\n")
        ledger = os.path.join(base, "ledger.csv")

        first = probe.start(base, {"INGEST_WORK_SECONDS": "1"})
        time.sleep(1.5)  # one file ingested, the next in progress
        took, _ = probe.terminate(first)
        if took is None:
            probe.kill(first)
            return ctx.failed("The worker did not stop within five seconds of SIGTERM.")
        after_stop = _names(ctx.read(ledger))

        second = probe.start(base, {"INGEST_WORK_SECONDS": "0.2"})
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline and len(_names(ctx.read(ledger))) < FILES:
            time.sleep(0.3)
        names = _names(ctx.read(ledger))
        probe.kill(second)
        evidence = f"after the stop: {after_stop}\nafter the restart: {names}"
        wanted = sorted(f"invoice-{n:03d}.txt" for n in range(1, FILES + 1))
        if sorted(set(names)) != wanted:
            return ctx.failed("After the restart the ledger does not hold every file.", evidence)
        repeated = sorted({n for n in names if names.count(n) > 1})
        if repeated:
            return ctx.failed(f"{len(repeated)} file(s) were ingested twice.", evidence)
        return ctx.passed("Every file is in the ledger exactly once.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
