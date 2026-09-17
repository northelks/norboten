"""The Claude Code plugin, as Claude Code itself reports it: a real run, kept as text.

    uv run python site/capture_plugin.py [--out site/captures/plugin-details.txt]

Installs `norboten-author` from this checkout into a throwaway Claude Code configuration, runs
`claude plugin details` on it, and writes what the command printed — unedited — with the Claude
Code version on the first line. The how-it-works page draws it in a terminal window in the Live
page's style. Nothing is signed in and no model is called. Needs `claude` on the PATH.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "site" / "captures" / "plugin-details.txt"


def run_details() -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="norboten-plugin-") as home:
        env = {
            "PATH": os.environ["PATH"],
            "HOME": home,
            "CLAUDE_CONFIG_DIR": str(Path(home) / "config"),
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_AUTOUPDATER": "1",
            "NO_COLOR": "1",
        }

        def claude(*args: str) -> str:
            done = subprocess.run(
                ["claude", *args], env=env, capture_output=True, text=True, timeout=120
            )
            if done.returncode != 0:
                raise SystemExit(f"claude {' '.join(args)} failed: {done.stdout}{done.stderr}")
            return done.stdout

        claude("plugin", "marketplace", "add", str(ROOT))
        claude("plugin", "install", "norboten-author@norboten")
        version = claude("--version").strip()
        return claude("plugin", "details", "norboten-author@norboten"), version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if shutil.which("claude") is None:
        print("claude is not on the PATH", file=sys.stderr)
        return 1
    output, version = run_details()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(f"{version}\n{output.rstrip()}\n")
    print(f"{args.out.relative_to(ROOT)}  {args.out.stat().st_size // 1024} KiB  ({version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
