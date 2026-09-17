"""The link check the site build runs on itself: every address is a directory that exists."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "site"))

import build  # noqa: E402


def page(out: Path, path: str, body: str) -> None:
    target = out / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"<!doctype html><html><body>{body}</body></html>")


def test_a_site_whose_links_all_land_has_no_faults(tmp_path):
    page(tmp_path, "index.html", '<a href="about/">About</a> <img src="static/logo.svg">')
    page(tmp_path, "about/index.html", '<a href="../">Home</a>')
    (tmp_path / "static").mkdir()
    (tmp_path / "static" / "logo.svg").write_text("<svg/>")
    assert build.broken_links(tmp_path) == []


def test_a_link_to_a_page_that_was_never_written_is_a_fault(tmp_path):
    page(tmp_path, "index.html", '<a href="journals/">Journals</a>')
    (tmp_path / "journals").mkdir()  # the directory exists, the page in it does not
    assert [f for f in build.broken_links(tmp_path) if "no such page" in f]


def test_a_link_that_names_index_html_is_a_fault(tmp_path):
    page(tmp_path, "index.html", '<a href="about/index.html">About</a>')
    page(tmp_path, "about/index.html", "About")
    faults = build.broken_links(tmp_path)
    assert len(faults) == 1 and "link to the directory" in faults[0]


def test_anchors_queries_and_other_sites_are_left_alone(tmp_path):
    page(
        tmp_path,
        "index.html",
        '<a href="#top">Top</a>'
        '<a href="https://docs.ansible.com/ansible/latest/vault_guide/index.html">Ansible</a>'
        '<a href="mailto:hi@norboten.org">Mail</a>'
        '<a href="about/?from=home#why">About</a>',
    )
    page(tmp_path, "about/index.html", "About")
    assert build.broken_links(tmp_path) == []
