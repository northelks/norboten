"""The learner's installer, against a stub uv: site/static/install.sh."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "site" / "static" / "install.sh"

FAKE_UV = """#!/bin/sh
# Paints its output the way uv does when FORCE_COLOR is set — into a pipe too — and, like uv,
# obeys NO_COLOR.
paint() {
    if [ -n "${NO_COLOR:-}" ]; then
        printf '%s\\n' "$1"
    else
        printf '\\033[36m%s\\033[39m\\n' "$1"
    fi
}
case "${1:-} ${2:-}" in
    "--version ") echo "uv 0.0.0-stub" ;;
    "tool install") echo "installed" >&2 ;;
    "tool dir") paint "@BIN@" ;;
    "tool update-shell") ;;
    *) echo "the stub uv was called with: $*" >&2; exit 1 ;;
esac
"""


def _stub(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(FAKE_UV.replace("@BIN@", str(bin_dir)))
    norboten = bin_dir / "norboten"
    norboten.write_text('#!/bin/sh\necho "norboten 9.9.9"\n')
    for path in (uv, norboten):
        path.chmod(0o755)
    return bin_dir


def _run(bin_dir, **env):
    return subprocess.run(
        ["sh", str(INSTALL_SH)],
        capture_output=True,
        text=True,
        timeout=60,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(bin_dir.parent),
            "NORBOTEN_YES": "1",
            "NORBOTEN_NO_LAUNCH": "1",
            **env,
        },
    )


@pytest.mark.skipif(shutil.which("sh") is None, reason="no POSIX shell")
def test_the_installed_norboten_is_found_in_a_shell_that_forces_color(tmp_path):
    # uv paints the path it prints when FORCE_COLOR is set; the escapes must not reach BIN_DIR.
    bin_dir = _stub(tmp_path)
    done = _run(bin_dir, FORCE_COLOR="3", CLICOLOR_FORCE="1")
    assert done.returncode == 0, done.stderr
    assert f"norboten 9.9.9 in {bin_dir}" in done.stderr


@pytest.mark.skipif(shutil.which("sh") is None, reason="no POSIX shell")
def test_a_missing_executable_still_fails(tmp_path):
    bin_dir = _stub(tmp_path)
    os.remove(bin_dir / "norboten")
    done = _run(bin_dir)
    assert done.returncode == 1
    assert "was installed but" in done.stderr
