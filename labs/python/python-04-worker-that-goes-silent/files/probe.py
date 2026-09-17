"""Start and stop the worker the way systemd does — shared by this lab's checks."""

import contextlib
import os
import signal
import subprocess


def start(base, env=None):
    """The worker with its output on a pipe, which is what a service writes to the journal
    through, and in a session of its own so a signal reaches the whole group."""
    return subprocess.Popen(
        ["python3", "/opt/ingest/worker.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
        env={
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "LC_ALL": "C.UTF-8",
            "INGEST_QUEUE": os.path.join(base, "queue"),
            "INGEST_LEDGER": os.path.join(base, "ledger.csv"),
            "INGEST_STATE": os.path.join(base, "done.json"),
            "INGEST_WORK_SECONDS": "0.3",
            **(env or {}),
        },
    )


def terminate(proc, timeout=5):
    """SIGTERM to the process group, as systemd stops a unit.

    Returns (seconds it took, output), or (None, "") when it was still running at the timeout.
    """
    import time

    os.killpg(proc.pid, signal.SIGTERM)
    started = time.monotonic()
    try:
        out = proc.communicate(timeout=timeout)[0]
    except subprocess.TimeoutExpired:
        return None, ""
    return time.monotonic() - started, out


def kill(proc):
    with contextlib.suppress(ProcessLookupError):
        os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=5)
