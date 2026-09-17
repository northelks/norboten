"""Journals: the format, what counts as finished, and the PDF."""

import pytest

from norboten.journal import (
    REQUIRED_SECTIONS,
    Journal,
    JournalError,
    Ref,
    all_journals,
    find,
    heading_for,
    parse,
    parse_ref,
)

GOOD = """---
title: A study document
topics: [storage-lvm]
minutes: 30
---

An opening paragraph that sets the scene. {filler}

## What you should be able to do after this

- one thing
- another thing

## The mechanism

How it works. {filler}

## A failure, walked through

Step by step. {filler}

## Common wrong turns

What people try. {filler}

## Cheat sheet

```console
lsblk
```

## Going deeper

- the storage topic journal

## Review

1. First question?

   > First answer.

2. Second question?

   > Second answer.

3. Third question?

   > Third answer.

4. Fourth question?

   > Fourth answer.

5. Fifth question?

   > Fifth answer.
"""


def _write(tmp_path, text: str, name: str = "journal.md"):
    path = tmp_path / name
    path.write_text(text)
    return path


def _good(tmp_path, **over):
    text = GOOD.format(filler="word " * 200)
    for old, new in over.items():
        text = text.replace(old, new)
    return parse(_write(tmp_path, text), id="x", kind="lab")


def test_a_finished_journal_has_nothing_wrong_with_it(tmp_path):
    journal = _good(tmp_path)
    assert journal.validate() == []
    assert journal.title == "A study document"
    assert journal.topics == ["storage-lvm"]
    assert journal.minutes == 30
    assert journal.sections == [*REQUIRED_SECTIONS[:-1], "Going deeper", "Review"]


def test_front_matter_is_required(tmp_path):
    with pytest.raises(JournalError, match="no YAML front matter"):
        parse(_write(tmp_path, "# just markdown\n"), id="x", kind="lab")


def test_a_title_is_required(tmp_path):
    with pytest.raises(JournalError, match="needs at least a title"):
        parse(_write(tmp_path, "---\ntopics: [bash]\n---\n\nbody\n"), id="x", kind="lab")


def test_broken_front_matter_says_so(tmp_path):
    text = "---\ntitle: [unclosed\n---\n\nbody\n"
    with pytest.raises(JournalError, match="not valid YAML"):
        parse(_write(tmp_path, text), id="x", kind="lab")


def test_a_missing_section_is_reported(tmp_path):
    journal = _good(tmp_path, **{"## Cheat sheet": "## Notes"})
    assert journal.validate() == ["missing section: ## Cheat sheet"]


def test_a_topic_journal_also_maps_symptoms_sets_exercises_and_names_sources(tmp_path):
    path = _write(tmp_path, GOOD.format(filler="word " * 200))
    topic = parse(path, id="storage-lvm", kind="topic")
    assert topic.validate() == [
        "no `covers:` in the front matter: one technical line of what it goes through",
        "missing section: ## Symptoms and causes",
        "missing section: ## Exercises",
        "missing section: ## Sources",
    ]


def test_an_unknown_topic_is_reported(tmp_path):
    journal = _good(tmp_path, **{"topics: [storage-lvm]": "topics: [lvm]"})
    assert "unknown topics: lvm" in journal.validate()


def test_a_journal_without_topics_is_reported(tmp_path):
    journal = _good(tmp_path, **{"topics: [storage-lvm]": "topics: []"})
    assert "no topics declared" in journal.validate()


def test_a_short_note_is_not_a_journal(tmp_path):
    text = GOOD.format(filler="")
    journal = parse(_write(tmp_path, text), id="x", kind="lab")
    assert any("study document, not a note" in p for p in journal.validate())


def test_a_question_without_an_answer_does_not_count(tmp_path):
    # The answer is what makes a review question useful a week later, so a question with no
    # `> answer` line is not one.
    journal = _good(tmp_path, **{"   > Fourth answer.": "   (to be written)"})
    assert len(journal.review) == 4
    assert any("review questions" in p for p in journal.validate())


def test_review_questions_come_back_as_pairs(tmp_path):
    pairs = _good(tmp_path).review
    assert len(pairs) == 5
    assert pairs[0] == ("First question?", "First answer.")


def test_code_blocks_do_not_count_towards_the_word_budget(tmp_path):
    with_code = _good(tmp_path, **{"lsblk": "word " * 500})
    without = _good(tmp_path)
    assert with_code.words == without.words


# -- the journals this repository actually ships -------------------------------------------------


def test_every_shipped_journal_is_finished():
    shipped = all_journals()
    assert shipped, "no journals in the checkout"
    for journal in shipped:
        assert journal.validate() == [], f"{journal.path}: {journal.validate()}"


def test_a_journal_is_found_by_lab_id_or_short_id():
    shipped = all_journals()
    first = shipped[0]
    assert find(first.id) is not None
    if first.kind == "lab":
        assert find(first.id.split("-")[0]).id == first.id


def test_an_unknown_journal_names_what_exists():
    with pytest.raises(JournalError, match="there are:"):
        find("no-such-journal")


def test_the_pdf_renders_with_a_cover_and_page_numbers():
    weasyprint = pytest.importorskip("weasyprint")
    from norboten.journal_pdf import to_html

    journal = all_journals()[0]
    html = to_html(journal)
    assert journal.title in html
    assert "@page" in html  # the print stylesheet is inlined, not linked
    document = weasyprint.HTML(string=html).render()
    assert len(document.pages) >= 2


def test_the_pdf_html_escapes_a_hostile_title(tmp_path):
    from norboten.journal_pdf import to_html

    journal = Journal(
        id="x",
        kind="lab",
        title="<script>alert(1)</script>",
        topics=["bash"],
        minutes=1,
        body="body\n",
        path=tmp_path / "journal.md",
    )
    html = to_html(journal)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_the_cheat_sheet_prints_on_its_own(tmp_path):
    from norboten.journal_pdf import PRINT_ON_OPEN, to_html

    journal = _good(tmp_path)
    assert journal.cheat_sheet == "```console\nlsblk\n```"
    html = to_html(journal, cheat_sheet=True, script=PRINT_ON_OPEN)
    assert "A study document — cheat sheet" in html and "lsblk" in html
    assert "First question?" not in html and "How it works." not in html
    assert 'location.hash === "#print"' in html
    assert "location.hash" not in to_html(journal)  # the TUI's PDF never carries a script


def test_the_walkthrough_and_its_subsections_are_one_block(tmp_path):
    path = tmp_path / "j.md"
    path.write_text(
        "---\ntitle: T\n---\n## The mechanism\n### A\n## A failure, walked through\n### Step one\n"
        "```\n## not a heading\n```\n## Cheat sheet\n### A\n"
    )
    j = parse(path, id="t", kind="topic")
    assert j.anchors == [
        "the-mechanism",
        "a",
        "a-failure-walked-through",
        "step-one",
        "cheat-sheet",
        "a-1",
    ]
    assert j.walkthrough_anchors == {"a-failure-walked-through", "step-one"}
    assert heading_for(j, "a-1") == "A"
    assert parse_ref("journal:t#a-1") == Ref("journal", "t", "a-1")
    assert parse_ref("man 5 fstab").label == "man 5 fstab"


def test_a_note_is_a_journal_with_no_topic_and_its_own_rules(tmp_path):
    from norboten.journal import parse

    body = "\n\n".join(f"## Part {i}\n\n" + "word " * 300 for i in range(3))
    path = tmp_path / "how-it-was-built.md"
    path.write_text(
        "---\ntitle: How it was built\nminutes: 10\ncovers: one line\n---\n\n"
        f"{body}\n\n## Sources\n\n- x\n"
    )
    note = parse(path, id=path.stem, kind="note")
    assert note.validate() == []  # no topics, no review, no cheat sheet — and finished

    path.write_text(
        path.read_text().replace("## Sources", "## Links").replace("covers: one line\n", "")
    )
    problems = parse(path, id=path.stem, kind="note").validate()
    assert "the last section is ## Sources" in problems and any("covers" in p for p in problems)
    assert any("topic slug" in p for p in parse(path, id="mcp", kind="note").validate())


def test_the_notes_in_the_checkout_are_listed_and_finished():
    notes = [j for j in all_journals() if j.kind == "note"]
    assert notes and all(n.validate() == [] for n in notes)
