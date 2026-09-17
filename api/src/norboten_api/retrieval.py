"""What the chat consultant is allowed to know: this repository, and nothing else.

The corpus is the documentation, the journals, the lab briefings and the theory questions — the
same material a learner can already read. Retrieval is BM25 over that, in memory, with no index to
build and no vector database to run.

BM25 rather than embeddings, deliberately. The corpus is a few hundred passages of technical prose
where the useful query terms are the exact ones in the text — `lvextend`, `fstab`, `SELinux
boolean` — and lexical scoring finds those better than a similarity search would, at no cost and
with an explanation a human can read. Embeddings become worth their weight when the corpus is
large enough that synonyms matter more than precision; this one is not, and pretending otherwise
would be the kind of unnecessary technology this project refuses elsewhere.

**No reference solution file is indexed**, and neither is a hint ladder, nor the section of a
journal that walks through its lab's fault step by step: the corpus is built only from material a
learner can already read. That is not the same as saying no command in it ever
appears in a solution — a journal that teaches LVM shows `lvextend -r`, and a theory explanation
about SELinux shows `setsebool -P`. Teaching the mechanism is the point of both. What must not
happen is handing someone the fix for the machine in front of them, and that is what the guard in
`agents/consultant.py` is for.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from norboten.labs.store import all_labs
from norboten.paths import repo_root
from norboten.quiz import bank as banks

#: BM25's usual constants: k1 controls how fast term frequency saturates, b how much document
#: length is penalised. These are the defaults from the literature and there is no reason to tune
#: them on a corpus this size.
K1 = 1.5
B = 0.75

#: Long documents are split so a passage is answerable on its own rather than being a whole page.
MAX_PASSAGE_WORDS = 180

_WORD = re.compile(r"[a-z0-9_.\-/]+")
STOP = frozenset(
    str.split(
        "a an the and or but if of to in on for with without from by is are was were be been "
        "being it its this that these those as at not no you your they them we our can may might "
        "will would should could do does did done has have had what which who when where why how"
    )
)


#: Words a learner uses for things the text names differently. A query term also looks for its group
#: at half weight, so an exact match still wins. Single tokens only, lower case, kept short and
#: general: it is part of the ranking, shipped to the browser in ask-index.json and read by people.
SYNONYMS: tuple[frozenset[str], ...] = tuple(
    frozenset(group.split())
    for group in (
        "docker container containers",
        "vm virtual machine",
        "uninstall delete remove",
        "internet online offline network",
        "backend server self-host host",
        "contribute write author",
        "login log sign signing",
        "password passwords credentials",
        "token tokens",
        "record recording recorded recordings stream streaming live",
        "restart reboot reboots rebooted",
        "reset restore rollback over",
        "mac macos apple m1 m2 m3 silicon arm64 aarch64",
        "windows wsl wsl2",
        "distro distros distribution distributions image images",
        "score grade graded grading",
        "hint hints clue",
        "pdf paper print",
        "cost costs price money",
        "visible see access",
        "timer timers schedule scheduled cron",
    )
)
_SYNONYMS_OF: dict[str, frozenset[str]] = {w: g for g in SYNONYMS for w in g}
SYNONYM_WEIGHT = 0.5


def expand(terms: list[str]) -> dict[str, float]:
    """Query terms with their weights: each term 1.0, its synonyms not already asked for 0.5."""
    weights = dict.fromkeys(terms, 1.0)
    for term in terms:
        for other in _SYNONYMS_OF.get(term, ()):
            weights.setdefault(other, SYNONYM_WEIGHT)
    return weights


def tokenize(text: str) -> list[str]:
    """Lowercase words, keeping the shapes that matter here: `/etc/fstab`, `ss -tlnp`, `-r`."""
    return [w for w in _WORD.findall(text.lower()) if w not in STOP and len(w) > 1]


@dataclass
class Passage:
    id: str
    title: str
    url: str  # where a reader can go and check
    kind: str  # docs | journal | lab | question
    text: str
    terms: Counter = field(default_factory=Counter)

    def __post_init__(self) -> None:
        if not self.terms:
            self.terms = Counter(tokenize(f"{self.title} {self.text}"))

    @property
    def length(self) -> int:
        return sum(self.terms.values())


@dataclass
class Hit:
    passage: Passage
    score: float


class Index:
    """A BM25 index over the corpus. Built once, held in memory; the corpus is under a megabyte."""

    def __init__(self, passages: list[Passage]) -> None:
        self.passages = passages
        self.average_length = sum(p.length for p in passages) / len(passages) if passages else 0.0
        self.document_frequency: Counter = Counter()
        for passage in passages:
            self.document_frequency.update(passage.terms.keys())
        self.total = len(passages)

    def idf(self, term: str) -> float:
        n = self.document_frequency.get(term, 0)
        if not n:
            return 0.0
        return math.log(1 + (self.total - n + 0.5) / (n + 0.5))

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        terms = expand(tokenize(query))
        if not terms or not self.passages:
            return []
        hits = []
        for passage in self.passages:
            score = 0.0
            for term, weight in terms.items():
                frequency = passage.terms.get(term, 0)
                if not frequency:
                    continue
                norm = 1 - B + B * (passage.length / (self.average_length or 1))
                bm25 = self.idf(term) * (frequency * (K1 + 1)) / (frequency + K1 * norm)
                score += weight * bm25
            if score > 0:
                hits.append(Hit(passage, round(score, 4)))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:limit]


# -- building the corpus -------------------------------------------------------------------------


def _split(text: str) -> list[str]:
    """Markdown into passages: by heading first, then by length, never mid-code-block."""
    blocks = re.split(r"\n(?=##{1,2} )", text)  # at every ## and ### heading
    out = []
    for block in blocks:
        words = block.split()
        if len(words) <= MAX_PASSAGE_WORDS:
            if block.strip():
                out.append(block.strip())
            continue
        chunk: list[str] = []
        in_code = False
        for line in block.splitlines():
            if line.startswith("```"):
                in_code = not in_code
            chunk.append(line)
            if not in_code and len(" ".join(chunk).split()) >= MAX_PASSAGE_WORDS:
                out.append("\n".join(chunk).strip())
                chunk = []
        if chunk and "\n".join(chunk).strip():
            out.append("\n".join(chunk).strip())
    return out


def _heading(text: str, fallback: str) -> str:
    match = re.search(r"^#{1,3} (.+)$", text, re.M)
    return match.group(1).strip() if match else fallback


DOC_PAGES = (
    ("faq", "FAQ"),
    ("getting-started", "Getting started"),
    ("tui-reference", "TUI reference"),
    ("writing-a-lab", "Writing a lab"),
    ("lab-spec", "Lab specification"),
    ("quiz-spec", "Theory question spec"),
    ("architecture", "Architecture"),
    ("data-model", "Data model"),
    ("pipelines", "Pipelines"),
    ("self-hosting", "Self-hosting and configuration"),
    ("deploy", "Deploying the server"),
    ("ci-cd", "CI/CD"),
    ("releasing", "Releasing"),
)


def build_corpus() -> list[Passage]:
    """Everything the consultant may quote. Solutions and hint ladders are not in here."""
    passages: list[Passage] = []
    root = repo_root()

    if root is not None:
        for slug, title in DOC_PAGES:
            path = root / "docs" / f"{slug}.md"
            if not path.is_file():
                continue
            for i, chunk in enumerate(_split(path.read_text())):
                passages.append(
                    Passage(
                        id=f"docs/{slug}#{i}",
                        title=f"{title} — {_heading(chunk, title)}",
                        url=f"/docs/{slug}/",
                        kind="docs",
                        text=chunk,
                    )
                )

        from norboten.journal import all_journals

        for journal in all_journals():
            section = ""
            for i, chunk in enumerate(_split(journal.without_walkthrough)):
                heading = _heading(chunk, journal.title)
                if top := re.match(r"## (.+)", chunk.lstrip()):
                    section = top.group(1).strip()
                # a cheat sheet has its own page, which is what someone asking for one wants
                page = "cheat-sheet.html" if section == "Cheat sheet" else ""
                passages.append(
                    Passage(
                        id=f"journal/{journal.id}#{i}",
                        title=f"{journal.title} — {heading}",
                        url=f"/journals/{journal.id}/{page}",
                        kind="journal",
                        text=chunk,
                    )
                )

    for lab in all_labs():
        m = lab.manifest
        passages.append(
            Passage(
                id=f"lab/{m.id}",
                title=f"{m.title} ({m.short_id})",
                url=f"/labs/{m.id}/",
                kind="lab",
                text=f"{lab.briefing}\n\nObjectives: " + "; ".join(m.objectives),
            )
        )

    for loaded in banks.all_banks():
        for question in loaded.bank.questions:
            passages.append(
                Passage(
                    id=f"question/{question.id}",
                    title=f"{loaded.bank.title}: {question.prompt[:60]}",
                    url="/labs/#theory",
                    kind="question",
                    text=f"{question.prompt}\n{question.explanation}\n"
                    + "; ".join(question.references),
                )
            )
    return passages


@lru_cache(maxsize=1)
def index() -> Index:
    return Index(build_corpus())


def passage_path(root: Path, passage: Passage) -> Path | None:  # pragma: no cover - debugging aid
    kind, _, rest = passage.id.partition("/")
    name = rest.split("#")[0]
    return {"docs": root / "docs" / f"{name}.md"}.get(kind)
