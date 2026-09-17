"""A hint's `journal:<id>#<anchor>` lands on the same heading in the TUI and on the site."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "site"))

import build  # noqa: E402  the site generator, next to its templates

from norboten import journal  # noqa: E402


def test_anchors_are_the_ids_the_site_gives_every_heading():
    md = build.markdown()
    for j in journal.all_journals():
        ids = re.findall(r'<h[123] id="([^"]+)"', md.render(j.body))
        assert j.anchors == ids, j.id


def test_the_lab_page_lists_its_hints_reading():
    from norboten.labs.store import find

    reading = build.reading(find("linux-01"))
    labels = [r["label"] for r in reading]
    assert "man 8 lsof" in labels
    assert any(r["href"].startswith("journals/linux-06-log-that-never-rotates/") for r in reading)
    assert not any(
        "journals/linux-01-disk-full/" in r["href"] for r in reading
    )  # its own: a button
