"""Executable verification: run a question's snippet and compare its output with the key.

The snippet runs in a throwaway container — no network, read-only root, a small tmpfs, memory and
process limits, a hard timeout — so a generated question can never touch the host.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from norboten.models import Question

IMAGES = {"bash": "ubuntu:26.04", "python": "python:3.12-slim"}
RUNNERS = {"bash": ["bash", "-c"], "python": ["python3", "-c"]}
TIMEOUT_S = 10


@dataclass
class VerifyResult:
    question_id: str
    ok: bool
    output: str
    expected: str
    error: str = ""


def docker_available() -> bool:
    """Whether a snippet can actually be run. A daemon that does not answer counts as absent.

    `docker info` against a stopped Docker Desktop hangs rather than failing, so the timeout is
    part of the answer, not an error to propagate.
    """
    if not shutil.which("docker"):
        return False
    try:
        probe = subprocess.run(["docker", "info"], capture_output=True, timeout=15)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return probe.returncode == 0


def run_snippet(runtime: str, code: str) -> subprocess.CompletedProcess:
    argv = [
        *("docker", "run", "--rm", "--network", "none", "--read-only"),
        *("--tmpfs", "/tmp:rw,size=16m", "--memory", "128m", "--pids-limit", "64"),
        *("--cap-drop", "ALL", "--security-opt", "no-new-privileges", "-w", "/tmp"),
        IMAGES[runtime],
        *RUNNERS[runtime],
        code,
    ]
    return subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_S + 20)


def verify(q: Question) -> VerifyResult:
    assert q.verify is not None
    expected = q.choice_text(q.answer[0]).strip()
    try:
        p = run_snippet(q.verify.runtime, q.verify.code)
    except subprocess.TimeoutExpired:
        return VerifyResult(q.id, False, "", expected, "timed out")
    output = p.stdout.strip()
    if p.returncode != 0 and not output:
        return VerifyResult(q.id, False, output, expected, p.stderr.strip()[-500:])
    return VerifyResult(q.id, output == expected, output, expected)
