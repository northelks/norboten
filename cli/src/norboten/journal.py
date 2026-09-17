"""Journals: the reading that goes with the labs.

A journal is one Markdown file with YAML front matter. It is a study document, not a manual page:
it explains the mechanism, walks through a failure, names the wrong turns people actually take,
and ends with questions you should be able to answer without looking.

Three kinds, the same format:

* a **lab journal** at `labs/<track>/<lab>/journal.md` — the machine in that lab, explained;
* a **topic journal** at `journals/<topic>.md` — one of the taxonomy topics, end to end;
* a **note** at `journals/notes/<slug>.md` — how something in Norboten itself was built and why,
  for someone building their own. A note teaches no taxonomy topic, so it rates nothing and has
  only the sections an engineering write-up has: free headings, and `## Sources` at the end.

The section headings are part of the contract, because the teaching devices are the point:

    ## What you should be able to do after this   a short list, in the imperative
    ## The mechanism                              how the thing actually works
    ## A failure, walked through                  one fault, diagnosed step by step
    ## Common wrong turns                         what people try that does not work, and why
    ## Cheat sheet                                the commands, in one place
    ## Review                                     questions for later, with their answers

and, for a topic journal, `## Symptoms and causes`, `## Exercises` and `## Sources`; for a lab
journal, `## Going deeper` — where the lab's hints send the reader next.

The TUI's Journals section (4) reads one and `e` exports it as a PDF; the site renders them all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from norboten import topics as taxonomy
from norboten.paths import content_root, local_labs_dir

#: In order. A journal missing one of these is not finished, and the linter says so.
REQUIRED_SECTIONS = (
    "What you should be able to do after this",
    "The mechanism",
    "A failure, walked through",
    "Common wrong turns",
    "Cheat sheet",
    "Review",
)

#: Beyond the core: a topic journal also maps symptoms to causes, sets exercises and names its
#: sources; a lab journal says where its hints' reading leads.
TOPIC_SECTIONS = ("Symptoms and causes", "Exercises", "Sources")
LAB_SECTIONS = ("Going deeper",)
NOTE_SECTIONS = ("Sources",)

#: The section that diagnoses one fault step by step. For a lab journal that is the fix for the
#: machine in that lab: the site shows it to a reader who chose to open the journal, but the chat
#: consultant does not index it (see `Journal.without_walkthrough`).
WALKTHROUGH = "A failure, walked through"

FRONT_MATTER = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)

#: Headings that get an anchor: the site's renderer gives ids to levels 1-3.
_HEADING = re.compile(r"^(#{1,3}) (.+?)\s*$", re.M)


def slug(title: str) -> str:
    """A heading's anchor, exactly as the site's renderer (mdit-py-plugins' anchors) makes it."""
    return re.sub(r"[^\w\u4e00-\u9fff\- ]", "", title.strip().lower().replace(" ", "-"))


def unique_slugs(titles: list[str]) -> list[str]:
    """Anchors for headings in document order; a repeated one gets -1, -2 … as on the site."""
    seen: set[str] = set()
    out = []
    for title in titles:
        base = anchor = slug(title)
        n = 1
        while anchor in seen:
            anchor = f"{base}-{n}"
            n += 1
        seen.add(anchor)
        out.append(anchor)
    return out


class JournalError(ValueError):
    pass


@dataclass
class Journal:
    id: str  # the lab id, the topic slug, or the note's slug
    kind: str  # "lab", "topic" or "note"
    title: str
    topics: list[str]
    minutes: int
    body: str  # markdown, front matter removed
    path: Path
    covers: str = ""  # one technical line: the mechanisms, commands and files it goes through

    @property
    def sections(self) -> list[str]:
        return re.findall(r"^## (.+)$", self.body, re.M)

    @property
    def anchors(self) -> list[str]:
        """Every heading's anchor, levels 1-3, in order (code blocks skipped)."""
        return unique_slugs([title for _, title in self._headings()])

    @property
    def walkthrough_anchors(self) -> set[str]:
        """The walkthrough's heading and everything under it: never a hint's reading, since for a
        lab journal it is that lab's fix."""
        out: set[str] = set()
        inside = False
        for (level, title), anchor in zip(self._headings(), self.anchors, strict=True):
            if level <= 2:
                inside = title == WALKTHROUGH
            if inside:
                out.add(anchor)
        return out

    def _headings(self) -> list[tuple[int, str]]:
        prose = re.sub(r"^```.*?^```", "", self.body, flags=re.M | re.S)
        return [(len(hashes), title) for hashes, title in _HEADING.findall(prose)]

    @property
    def words(self) -> int:
        return len(re.findall(r"\b\w+\b", re.sub(r"```.*?```", "", self.body, flags=re.S)))

    @property
    def without_walkthrough(self) -> str:
        """The body minus the walkthrough: the mechanism, the wrong turns, the cheat sheet."""
        return re.sub(
            rf"^## {re.escape(WALKTHROUGH)}\s*\n.*?(?=^## |\Z)", "", self.body, flags=re.M | re.S
        )

    @property
    def cheat_sheet(self) -> str:
        """The commands, in one place: the section a reader prints and keeps beside the keyboard."""
        return _section(self.body, "Cheat sheet").strip()

    @property
    def review(self) -> list[tuple[str, str]]:
        """The review questions, as (question, answer) pairs.

        The convention is a numbered question followed by an indented `> answer` line, so the
        Markdown reads correctly on its own and the site can still hide the answers.
        """
        block = _section(self.body, "Review")
        pairs = []
        for match in re.finditer(r"^\d+\.\s+(.+?)\n+\s*> ?(.+?)$", block, re.M | re.S):
            question = " ".join(match.group(1).split())
            answer = " ".join(match.group(2).split())
            pairs.append((question, answer))
        return pairs

    def validate(self) -> list[str]:
        """Everything wrong with this journal, in plain words. Empty means it is finished."""
        if self.kind == "note":
            return self._validate_note()
        problems = []
        found = self.sections
        extra = TOPIC_SECTIONS if self.kind == "topic" else LAB_SECTIONS
        if self.kind == "topic" and not self.covers:
            problems.append(
                "no `covers:` in the front matter: one technical line of what it goes through"
            )
        for wanted in (*REQUIRED_SECTIONS, *extra):
            if wanted not in found:
                problems.append(f"missing section: ## {wanted}")
        unknown = [t for t in self.topics if t not in taxonomy.BY_SLUG]
        if unknown:
            problems.append(f"unknown topics: {', '.join(unknown)}")
        if not self.topics:
            problems.append("no topics declared")
        if self.words < 800:
            problems.append(f"only {self.words} words; a journal is a study document, not a note")
        if len(self.review) < 5:
            problems.append(f"only {len(self.review)} review questions with answers; five minimum")
        return problems

    def _validate_note(self) -> list[str]:
        problems = []
        if not self.covers:
            problems.append("no `covers:` in the front matter: one line of what it goes through")
        if self.id in taxonomy.BY_SLUG:
            problems.append(f"{self.id!r} is a topic slug; a note is named for what it describes")
        unknown = [t for t in self.topics if t not in taxonomy.BY_SLUG]
        if unknown:
            problems.append(f"unknown topics: {', '.join(unknown)}")
        if len(self.sections) < 4:
            problems.append("fewer than four sections; a note is a write-up, not a paragraph")
        if self.sections[-1:] != list(NOTE_SECTIONS):
            problems.append("the last section is ## Sources")
        if self.words < 800:
            problems.append(f"only {self.words} words; a note explains the reasoning, not a fact")
        return problems


def _section(body: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    return match.group(1) if match else ""


def parse(path: Path, *, id: str, kind: str) -> Journal:
    text = path.read_text()
    match = FRONT_MATTER.match(text)
    if not match:
        raise JournalError(f"{path.name}: no YAML front matter")
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as e:
        raise JournalError(f"{path.name}: front matter is not valid YAML: {e}") from None
    if not isinstance(meta, dict) or "title" not in meta:
        raise JournalError(f"{path.name}: front matter needs at least a title")
    return Journal(
        id=id,
        kind=kind,
        title=str(meta["title"]),
        topics=list(meta.get("topics") or []),
        minutes=int(meta.get("minutes") or 0),
        body=match.group(2).strip() + "\n",
        path=path,
        covers=" ".join(str(meta.get("covers") or "").split()),
    )


def journals_dir() -> Path | None:
    root = content_root()
    return root / "journals" if root else None


def all_journals() -> list[Journal]:
    """Every journal in the checkout: the topic ones first, then the notes, then one per lab that
    has one."""
    out: list[Journal] = []
    directory = journals_dir()
    if directory and directory.is_dir():
        for path in sorted(directory.glob("*.md")):
            out.append(parse(path, id=path.stem, kind="topic"))
        for path in sorted((directory / "notes").glob("*.md")):
            out.append(parse(path, id=path.stem, kind="note"))
    labs = local_labs_dir()
    if labs and labs.is_dir():
        for path in sorted(labs.rglob("journal.md")):
            out.append(parse(path, id=path.parent.name, kind="lab"))
    return out


@dataclass(frozen=True)
class Ref:
    """One entry of a hint's reading (`refs` in hints.yaml)."""

    kind: str  # "journal", "man" or "url"
    target: str  # the journal id, "5 fstab", or the URL
    anchor: str = ""

    @property
    def label(self) -> str:
        if self.kind == "journal":
            return f"journal {self.target} § {self.anchor}"
        if self.kind == "man":
            return f"man {self.target}"
        return self.target


def parse_ref(text: str) -> Ref:
    if text.startswith("journal:"):
        target, _, anchor = text.removeprefix("journal:").partition("#")
        return Ref("journal", target, anchor)
    if text.startswith("man "):
        return Ref("man", text.removeprefix("man "))
    return Ref("url", text)


def heading_for(journal: Journal, anchor: str) -> str | None:
    """The heading text an anchor points at, or None when the journal has no such heading."""
    for (_, title), found in zip(journal._headings(), journal.anchors, strict=True):
        if found == anchor:
            return title
    return None


def find(query: str) -> Journal:
    """A journal by topic slug, lab id or lab short id."""
    available = all_journals()
    for journal in available:
        if journal.id == query:
            return journal
    for journal in available:
        if journal.id.startswith(query) or journal.id.split("-")[0] == query:
            return journal
    known = ", ".join(j.id for j in available) or "none yet"
    raise JournalError(f"no journal for {query!r}; there are: {known}")
