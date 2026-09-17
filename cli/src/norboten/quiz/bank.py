"""Question banks: quizzes/<topic>.yaml and each lab's theory.yaml — docs/quiz-spec.md.

A learner's own questions (`g` on Theory) are banks too, in ~/.norboten/quizzes: `own_banks()`
loads them apart from the published ones, which `all_banks()` returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from norboten.labs.manifest import LabError
from norboten.models import Question, QuestionBank
from norboten.paths import content_root, local_labs_dir, norboten_home


@dataclass(frozen=True)
class LoadedBank:
    bank: QuestionBank
    path: Path
    lab_id: str | None = None  # set for a lab's theory.yaml
    own: bool = False  # the learner's own questions: practice only, never rated

    @property
    def topic(self) -> str:
        return self.bank.topic


def quizzes_dir() -> Path | None:
    root = content_root()
    return root / "quizzes" if root else None


def own_dir() -> Path:
    return norboten_home() / "quizzes"


def load(path: Path, lab_id: str | None = None, own: bool = False) -> LoadedBank:
    try:
        data = yaml.safe_load(path.read_text())
        return LoadedBank(QuestionBank.model_validate(data), path, lab_id, own)
    except (OSError, yaml.YAMLError) as e:
        raise LabError(f"{path}: {e}") from None
    except ValidationError as e:
        details = "\n".join(
            f"  {'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
        )
        raise LabError(f"{path}: invalid question bank\n{details}") from None


def all_banks() -> list[LoadedBank]:
    banks: list[LoadedBank] = []
    qdir = quizzes_dir()
    if qdir and qdir.is_dir():
        banks += [load(p) for p in sorted(qdir.glob("*.yaml"))]
    labs = local_labs_dir()
    if labs and labs.is_dir():
        for theory in sorted(labs.rglob("theory.yaml")):
            if "_template" not in theory.parts:
                banks.append(load(theory, lab_id=theory.parent.name))
    return banks


def own_banks() -> list[LoadedBank]:
    """The learner's own banks. One that no longer loads is skipped, not an error."""
    out = []
    for path in sorted(own_dir().glob("*.yaml")):
        try:
            out.append(load(path, own=True))
        except LabError:
            continue
    return out


def topic_banks() -> list[LoadedBank]:
    return [b for b in all_banks() if b.lab_id is None]


def find_topic(topic: str) -> LoadedBank:
    for b in all_banks():
        if topic in (b.topic, b.lab_id):
            return b
    raise LabError(f"no theory topic {topic!r}")


def duplicate_ids(banks: list[LoadedBank]) -> list[str]:
    seen: dict[str, Path] = {}
    dupes = []
    for b in banks:
        for q in b.bank.questions:
            if q.id in seen:
                dupes.append(f"{q.id}: in {seen[q.id]} and {b.path}")
            seen[q.id] = b.path
    return dupes


def questions_with_verify(banks: list[LoadedBank]) -> list[tuple[LoadedBank, Question]]:
    return [(b, q) for b in banks for q in b.bank.questions if q.verify]
