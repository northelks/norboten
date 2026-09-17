"""The Question Generator and the pipeline a question has to pass before it is kept as a draft.

    generate → schema → blind cross-model solve → critic → execute → dedup

It runs on the machine of whoever drafts: a maintainer filling a bank, or a learner making questions
of their own, on their own Claude Code or keys. A question survives only if every stage passes, and
it keeps its provenance: which model wrote it, which models answered it without seeing the key and
what they answered, what the critic said, and what the snippet actually printed. See
docs/quiz-spec.md section 5.
"""

from __future__ import annotations

import difflib
import random
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from norboten.models import Question
from norboten.questions import providers
from norboten.quiz import verify as sandbox

#: On a subscription, through the local Claude Code: Opus writes, Sonnet and Haiku answer blind.
DEFAULT_GENERATOR = "claude-code/opus"
DEFAULT_VERIFIERS = ["claude-code/sonnet", "claude-code/haiku"]
DEFAULT_MIN_VERIFIERS = 2

#: With keys instead of Claude Code: who may write and who may answer blind, best first.
KEY_WRITERS = ["claude-opus-5", "gpt-5-codex", "gemini-3-pro"]
KEY_SOLVERS = ["claude-sonnet-5", "claude-haiku-4-5", "gpt-5-codex", "gemini-3-pro"]


def choose_models(config: providers.Config | None = None) -> tuple[str, list[str]] | None:
    """The writer and the blind solvers this machine can reach, or None with fewer than a writer
    and two solvers. Claude Code on a subscription first; exported keys add other families; the
    models a local Ollama has pulled come last — the same order as the tutor's."""
    config = config or providers.local_config(probe_ollama=True)
    pulled = providers.ollama_models(config.ollama_url)
    writers = providers.usable_models([DEFAULT_GENERATOR, *KEY_WRITERS], config) + pulled
    if not writers:
        return None
    generator = writers[0]
    solvers = providers.usable_models([*DEFAULT_VERIFIERS, *KEY_SOLVERS], config) + pulled
    solvers = [m for m in dict.fromkeys(solvers) if m != generator]
    if len(solvers) < DEFAULT_MIN_VERIFIERS:
        return None
    return generator, solvers


GENERATOR_SYSTEM = """You write multiple-choice questions for Linux engineers practising on
Norboten. A question must test understanding that matters on a real machine, not trivia.

Rules:
- Exactly one correct choice for type "single"; one or more for type "multiple".
- 4 choices, each plausible to someone who half-knows the topic. Never "all of the above",
  "none of the above" or "both a and b".
- The explanation says why the answer is right AND why the tempting wrong ones are wrong, naming
  a choice by what it says, never by its letter: the choices are shown in a random order.
- Give at least one reference: a man page ("man 5 fstab") or an official documentation URL.
- The prompt is at most 600 characters and each choice at most 300. A config file or a
  snippet goes in `code`, once — never repeated inside the prompt.
- If the question asks what a command or snippet prints, put the exact snippet in `verify.code`
  with its runtime, and make the correct choice's text exactly what it prints (stripped).
  Otherwise leave `verify` null: it is not a place for a reproduction script.
- No question about a specific distribution version number, a release date, or anything that
  changes with time."""

SOLVER_SYSTEM = """You are answering a multiple-choice question for a Linux certification. You
are not told the answer. Choose the ids you believe are correct. If more than one answer is
defensible, or the question is ambiguous, say so with ambiguous=true."""

CRITIC_SYSTEM = """You review multiple-choice questions for a Linux training platform. Report a
question as invalid if: a stated fact is wrong; more than one choice is defensible; the key is
wrong; the wording gives the answer away; or the reference does not support the answer. Be
strict; a wrong question teaches a wrong thing."""


class DraftChoice(BaseModel):
    id: Literal["a", "b", "c", "d", "e", "f"]
    text: str = Field(max_length=300)


class DraftVerify(BaseModel):
    runtime: Literal["bash", "python"]
    code: str


class Draft(BaseModel):
    type: Literal["single", "multiple"]
    difficulty: int = Field(ge=1, le=5)
    prompt: str = Field(max_length=600)
    code: str | None = None
    code_lang: Literal["bash", "python", "hcl", "yaml", "json", "text"] = "text"
    choices: list[DraftChoice] = Field(min_length=3, max_length=6)
    answer: list[Literal["a", "b", "c", "d", "e", "f"]]
    explanation: str
    references: list[str]
    tags: list[str] = Field(default_factory=list)
    verify: DraftVerify | None = None


class SolveAnswer(BaseModel):
    answer: list[Literal["a", "b", "c", "d", "e", "f"]]
    ambiguous: bool = False
    note: str = ""


class Critique(BaseModel):
    valid: bool
    issues: list[str] = Field(default_factory=list)


@dataclass
class Provenance:
    generator: str = ""
    solvers: list[dict] = field(default_factory=list)
    critic: dict = field(default_factory=dict)
    execution: dict = field(default_factory=dict)


@dataclass
class Outcome:
    accepted: bool
    question: Question | None = None
    provenance: Provenance = field(default_factory=Provenance)
    rejected_by: str = ""
    reason: str = ""


def _next_id(topic: str, taken: set[str]) -> str:
    prefix = re.sub(r"[^a-z0-9]", "", topic.lower())[:8] or "gen"
    n = 1
    while f"{prefix}-{n:03d}" in taken:
        n += 1
    return f"{prefix}-{n:03d}"


def to_question(draft: Draft, question_id: str) -> Question:
    """Draft → the repo's own Question model, which enforces docs/quiz-spec.md section 2."""
    data = draft.model_dump()
    data["id"] = question_id
    if data.get("verify"):
        data["verify"]["expect"] = "output_is_answer"
    # A writer model puts the right answer first far more often than chance; the solvers and the
    # bank get the choices in an order fixed by the id instead.
    return Question.model_validate(data).shuffled(random.Random(question_id))


def ask_to_solve(
    question: Question, model: str, config: providers.Config | None = None
) -> SolveAnswer:
    choices = "\n".join(f"{c.id}) {c.text}" for c in question.choices)
    code = f"\n\n{question.code}\n" if question.code else ""
    return providers.ask(
        model=model,
        system=SOLVER_SYSTEM,
        user=f"{question.prompt}{code}\n\n{choices}\n\nWhich ids are correct?",
        schema=SolveAnswer,
        max_tokens=800,
        config=config,
    )


def ask_to_review(
    question: Question, model: str, config: providers.Config | None = None
) -> Critique:
    return providers.ask(
        model=model,
        system=CRITIC_SYSTEM,
        user=(
            f"Question: {question.prompt}\n"
            + (f"Snippet:\n{question.code}\n" if question.code else "")
            + "Choices:\n"
            + "\n".join(f"{c.id}) {c.text}" for c in question.choices)
            + f"\nKey: {', '.join(question.answer)}\n"
            f"Explanation: {question.explanation}\n"
            f"References: {', '.join(question.references)}"
        ),
        schema=Critique,
        max_tokens=800,
        config=config,
    )


def is_duplicate(prompt: str, existing: list[str], threshold: float = 0.85) -> str | None:
    flat = re.sub(r"\s+", " ", prompt).strip().lower()
    for other in existing:
        ratio = difflib.SequenceMatcher(None, flat, re.sub(r"\s+", " ", other).strip().lower())
        if ratio.ratio() >= threshold:
            return other
    return None


def generate(
    topic: str,
    *,
    difficulty: int = 2,
    existing_prompts: list[str] | None = None,
    taken_ids: set[str] | None = None,
    id_prefix: str | None = None,
    generator_model: str | None = None,
    verifier_models: list[str] | None = None,
    min_verifiers: int | None = None,
    run_sandbox: bool = True,
    keep_unrun: bool = True,
    config: providers.Config | None = None,
) -> Outcome:
    """`run_sandbox` runs a question's snippet in Docker; without it, `keep_unrun` decides whether
    a question whose snippet was never run is kept (a maintainer reviews it) or rejected."""
    config = config or providers.local_config()
    generator = generator_model or DEFAULT_GENERATOR
    verifiers = [
        m
        for m in providers.usable_models(verifier_models or DEFAULT_VERIFIERS, config)
        if m != generator
    ]
    needed = min_verifiers if min_verifiers is not None else DEFAULT_MIN_VERIFIERS
    prov = Provenance(generator=generator)

    if len(verifiers) < needed:
        return Outcome(
            False,
            provenance=prov,
            rejected_by="setup",
            reason=f"{len(verifiers)} verifier models available, {needed} required",
        )

    # 1 — generate
    try:
        draft = providers.ask(
            model=generator,
            system=GENERATOR_SYSTEM,
            user=(
                f"Write one question about: {topic}. Difficulty {difficulty} of 5. "
                "It must be answerable from a shell on a current Linux system."
            ),
            schema=Draft,
            max_tokens=2000,
            config=config,
        )
    except providers.ProviderError as e:
        return Outcome(False, provenance=prov, rejected_by="generator", reason=str(e))

    # 2 — schema and spec
    try:
        question = to_question(draft, _next_id(id_prefix or topic, taken_ids or set()))
    except ValidationError as e:
        return Outcome(False, provenance=prov, rejected_by="schema", reason=str(e).split("\n")[1:3])

    # 3 — blind cross-model solve
    agreeing = 0
    for model in verifiers[: max(needed, 2)]:
        try:
            solved = ask_to_solve(question, model, config)
        except providers.ProviderError as e:
            prov.solvers.append({"model": model, "error": str(e)})
            continue
        agrees = set(solved.answer) == set(question.answer) and not solved.ambiguous
        prov.solvers.append(
            {
                "model": model,
                "answer": sorted(solved.answer),
                "ambiguous": solved.ambiguous,
                "agrees": agrees,
                "note": solved.note[:200],
            }
        )
        if not agrees:
            return Outcome(
                False,
                provenance=prov,
                rejected_by="blind_solve",
                reason=f"{model} answered {sorted(solved.answer)}, key is {sorted(question.answer)}"
                + (" and called it ambiguous" if solved.ambiguous else ""),
            )
        agreeing += 1
    if agreeing < needed:
        return Outcome(
            False,
            provenance=prov,
            rejected_by="blind_solve",
            reason=f"only {agreeing} of {needed} verifiers answered",
        )

    # 4 — critic
    critic_model = verifiers[0]
    try:
        critique = ask_to_review(question, critic_model, config)
    except providers.ProviderError as e:
        return Outcome(False, provenance=prov, rejected_by="critic", reason=str(e))
    prov.critic = {"model": critic_model, "valid": critique.valid, "issues": critique.issues}
    if not critique.valid:
        return Outcome(
            False,
            provenance=prov,
            rejected_by="critic",
            reason="; ".join(critique.issues)[:300] or "the critic rejected it",
        )

    # 5 — run the snippet, if the question has one
    if question.verify and run_sandbox:
        result = sandbox.verify(question)
        prov.execution = {
            "ok": result.ok,
            "output": result.output[:200],
            "expected": result.expected[:200],
            "error": result.error[:200],
        }
        if not result.ok:
            return Outcome(
                False,
                provenance=prov,
                rejected_by="execution",
                reason=f"the snippet printed {result.output!r}, the key says {result.expected!r}",
            )

    if question.verify and not run_sandbox and not keep_unrun:
        return Outcome(
            False,
            provenance=prov,
            rejected_by="execution",
            reason="its snippet was not run: Docker is not available",
        )

    # 6 — dedup
    near = is_duplicate(question.prompt, existing_prompts or [])
    if near:
        return Outcome(False, provenance=prov, rejected_by="duplicate", reason=near[:120])

    return Outcome(True, question=question, provenance=prov)
