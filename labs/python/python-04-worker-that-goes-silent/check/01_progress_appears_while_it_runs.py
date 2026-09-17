import os
import shutil
import tempfile
import time
from importlib.machinery import SourceFileLoader

DEADLINE = 12.0


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
        proc = probe.start(base)
        os.set_blocking(proc.stdout.fileno(), False)
        seen, deadline = [], time.monotonic() + DEADLINE
        while time.monotonic() < deadline and len(seen) < 3:
            line = proc.stdout.readline()
            if line:
                seen.append(line.strip())
            else:
                time.sleep(0.2)
        rows = (ctx.read(os.path.join(base, "ledger.csv")) or "").splitlines()
        probe.kill(proc)
        evidence = f"after {DEADLINE:.0f}s\nlines read: {seen}\nledger rows: {rows}"
        if len(rows) < 3:
            return ctx.failed("The worker did not ingest the three files.", evidence)
        if len(seen) < 3:
            return ctx.failed(
                f"The ledger holds {len(rows)} rows, and only {len(seen)} progress lines "
                "reached the reader while the worker ran.",
                evidence,
            )
        return ctx.passed("Every ingested file was reported while the worker ran.", evidence)
    finally:
        shutil.rmtree(base, ignore_errors=True)
