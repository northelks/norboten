import shutil
from pathlib import Path

import pytest

from norboten.labs.lint import lint_lab, lint_topic_journals, lint_tree
from norboten.paths import repo_root

TEMPLATE = repo_root() / "labs" / "_template"


@pytest.fixture
def lab(tmp_path: Path) -> Path:
    dst = tmp_path / "linux-00-template"
    shutil.copytree(TEMPLATE, dst)
    return dst


def test_template_is_clean():
    assert lint_lab(TEMPLATE) == []


def test_every_lab_in_repo_is_clean():
    problems = {str(p): e for p, e in lint_tree(repo_root() / "labs").items() if e}
    assert problems == {}


def test_directory_must_match_id(lab: Path):
    renamed = lab.with_name("something-else")
    lab.rename(renamed)
    assert any("directory name must equal id" in e for e in lint_lab(renamed))


def test_check_file_without_manifest_entry(lab: Path):
    (lab / "check" / "02_extra.py").write_text("def check(ctx):\n    return ctx.passed('x')\n")
    assert any("do not match check/ files" in e for e in lint_lab(lab))


def test_missing_hint_ladder(lab: Path):
    (lab / "hints.yaml").write_text("checks: {}\n")
    assert any("no hints for" in e for e in lint_lab(lab))


def test_third_party_import_is_rejected(lab: Path):
    (lab / "check" / "01_motd_world_readable.py").write_text(
        "import requests\n\n\ndef check(ctx):\n    return ctx.passed('x')\n"
    )
    assert any("imports 'requests'" in e for e in lint_lab(lab))


def test_missing_entrypoint_is_rejected(lab: Path):
    (lab / "break" / "01_example_fault.py").write_text("def broken(ctx):\n    pass\n")
    assert any("must define apply(ctx)" in e for e in lint_lab(lab))


def test_early_hint_may_not_name_solution_path(lab: Path):
    text = (
        (lab / "hints.yaml")
        .read_text()
        .replace("Only root can read the message.", "Only root can read /srv/example/motd.")
    )
    (lab / "hints.yaml").write_text(text)
    assert any("level_1 names /srv/example/motd" in e for e in lint_lab(lab))


def test_solution_for_unlisted_image(lab: Path):
    (lab / "solution" / "rocky-10.sh").write_text("#!/bin/sh\n")
    assert any("per-image solution" in e for e in lint_lab(lab))


def test_missing_briefing(lab: Path):
    (lab / "briefing.md").unlink()
    assert any("missing briefing.md" in e for e in lint_lab(lab))


TOPIC_JOURNAL = """---
title: A topic, end to end
topics: [{topic}]
minutes: 30
covers: one line of what it goes through
---

Opening. {filler}

## What you should be able to do after this

- one thing

## The mechanism

{filler}

## A failure, walked through

{filler}

## Common wrong turns

{filler}

## Cheat sheet

```console
true
```

## Symptoms and causes

| a | b |
|---|---|
| x | y |

## Exercises

1. One.

## Sources

- `man 1 ls`

## Review

""" + "".join(f"{i}. Question {i}?\n\n   > Answer {i}.\n\n" for i in range(1, 6))


def test_every_topic_journal_in_repo_is_clean():
    problems = {str(p): e for p, e in lint_topic_journals(repo_root() / "journals").items() if e}
    assert problems == {}


def test_a_topic_journal_is_named_after_its_topic(tmp_path: Path):
    body = TOPIC_JOURNAL.replace("{filler}", "word " * 250)
    (tmp_path / "containers.md").write_text(body.replace("{topic}", "containers"))
    (tmp_path / "boxes.md").write_text(body.replace("{topic}", "containers"))
    (tmp_path / "ansible.md").write_text(body.replace("{topic}", "terraform"))
    results = {p.name: e for p, e in lint_topic_journals(tmp_path).items()}
    assert results["containers.md"] == []
    assert any("not a topic slug" in e for e in results["boxes.md"])
    assert any("does not declare its own topic" in e for e in results["ansible.md"])


def test_a_broken_theory_bank_fails_the_lab(tmp_path):
    lab = tmp_path / "lab"
    shutil.copytree(TEMPLATE, lab)
    (lab / "theory.yaml").write_text("schema_version: 1\ntopic: x\nquestions:\n  - prompt: a: b\n")
    problems = lint_lab(lab)
    assert any("theory.yaml" in p for p in problems)


def test_a_module_the_image_installs_is_importable_only_on_that_image(tmp_path: Path):
    claude_lab = repo_root() / "labs" / "claude" / "claude-01-the-bot-that-deleted-the-drafts"
    assert lint_lab(claude_lab) == []
    elsewhere = tmp_path / "linux-00-template"
    shutil.copytree(TEMPLATE, elsewhere)
    (elsewhere / "check" / "01_motd_world_readable.py").write_text(
        "import claude_lab\n\n\ndef check(ctx):\n    return ctx.passed('x')\n"
    )
    assert any("imports 'claude_lab'" in e for e in lint_lab(elsewhere))


def _refs(lab: Path, block: str) -> None:
    text = (lab / "hints.yaml").read_text()
    head = text.split("    refs:")[0]
    (lab / "hints.yaml").write_text(head + "    refs:\n" + block)


def test_a_hint_may_point_at_a_journal_heading_a_man_page_or_documentation(lab: Path):
    _refs(
        lab,
        '      2: ["man 1 chmod", "journal:networking#routes-ask-the-kernel"]\n'
        '      3: ["https://man7.org/linux/man-pages/man1/chmod.1.html"]\n',
    )
    assert lint_lab(lab) == []


@pytest.mark.parametrize(
    ("ref", "level", "error"),
    [
        ("journal:networking#no-such-heading", 2, "has no heading #no-such-heading"),
        ("journal:no-such-journal#x", 2, "no journal 'no-such-journal'"),
        ("journal:linux-01-disk-full#a-failure-walked-through", 3, "points into a walkthrough"),
    ],
)
def test_a_reference_that_goes_nowhere_or_to_the_fix_is_refused(lab: Path, ref, level, error):
    _refs(lab, f'      {level}: ["{ref}"]\n')
    assert any(error in e for e in lint_lab(lab)), lint_lab(lab)


def test_the_labs_own_journal_waits_for_level_three(lab: Path):
    import yaml

    lab_id = yaml.safe_load((lab / "lab.yaml").read_text())["id"]
    (lab / "journal.md").write_text((repo_root() / "labs" / "hello" / "journal.md").read_text())
    _refs(lab, f'      2: ["journal:{lab_id}#ten-characters"]\n')
    assert any("from level 3" in e for e in lint_lab(lab))
    _refs(lab, f'      3: ["journal:{lab_id}#ten-characters"]\n')
    assert lint_lab(lab) == []


def test_a_malformed_reference_is_a_schema_error(lab: Path):
    _refs(lab, '      2: ["see the fstab page"]\n')
    assert any("invalid hints" in e for e in lint_lab(lab))
