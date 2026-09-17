"""Turn the TUI's SVG captures into PNGs, for the places that will not render SVG.

GitHub's README is the one that matters: it strips what makes a Textual capture a capture, so the
front page ships PNGs instead. Everything else on the site uses the SVGs directly.

    uv run python site/capture_png.py                # every capture named below
    uv run python site/capture_png.py tui-check      # one of them

It drives a headless Chrome, which is the browser these captures are proofed in anyway. Without
one it says so and changes nothing — the PNGs in the repository stay as they are.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAPTURES = ROOT / "site" / "static" / "captures"
OUT = ROOT / "docs" / "images"
WIDTH = 1200

#: What the README shows, one picture per section.
README_CAPTURES = (
    "tui-system",
    "tui-labs",
    "tui-check",
    "tui-quiz",
    "tui-journals",
    "tui-play",
    "tui-you",
)

BROWSERS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome",
    "chromium",
    "chromium-browser",
)


def browser() -> str | None:
    for candidate in BROWSERS:
        found = candidate if Path(candidate).is_file() else shutil.which(candidate)
        if found:
            return found
    return None


def height_of(svg: Path) -> int:
    """The capture's own aspect ratio, from its viewBox, scaled to WIDTH."""
    head = svg.read_text()[:4000]
    box = head.split('viewBox="', 1)[1].split('"', 1)[0].split()
    return round(WIDTH * float(box[3]) / float(box[2]))


def render(chrome: str, slug: str) -> Path:
    svg = CAPTURES / f"{slug}.svg"
    target = OUT / f"{slug}.png"
    OUT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / "page.html"
        page.write_text(
            "<!doctype html><meta charset='utf-8'>"
            "<style>html,body{margin:0;background:#0a0e0c}img{display:block;width:100%}</style>"
            f"<img src='{svg.as_uri()}'>"
        )
        subprocess.run(
            [
                chrome,
                "--headless",
                "--disable-gpu",
                "--hide-scrollbars",
                f"--window-size={WIDTH},{height_of(svg)}",
                f"--screenshot={target}",
                "--virtual-time-budget=4000",
                page.as_uri(),
            ],
            check=True,
            capture_output=True,
        )
    return target


def main(argv: list[str]) -> int:
    chrome = browser()
    if not chrome:
        print("no headless Chrome found; the PNGs in docs/images are unchanged")
        return 0
    for slug in argv or README_CAPTURES:
        if not (CAPTURES / f"{slug}.svg").is_file():
            print(f"no capture {slug}")
            return 1
        target = render(chrome, slug)
        print(f"{target.relative_to(ROOT)}  {target.stat().st_size // 1024} KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
