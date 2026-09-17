"""Draft questions through the whole pipeline and keep what passes, with its provenance.

    norboten dev draft-questions networking --count 5 \\
        [--about "firewalld zones and runtime versus permanent rules"] [--difficulty 3] \\
        [--generator claude-code/opus] [--verifiers claude-code/sonnet,claude-code/haiku]

Each question is generated, held to the spec, answered blind by the verifier models, reviewed by a
critic, its snippet run in Docker, and compared with every question already known
(`pipeline.generate`). By default every model is reached through the local Claude Code on a
subscription (`claude-code/<model>`), so no API key is needed; any id the providers know works, and
mixing vendors (`claude-code/sonnet,gpt-5-codex`) makes the blind solve stronger than one family
checking itself.

A maintainer's drafts go to `quizzes/_drafts/<topic>.yaml`, which is not a bank (only
`quizzes/*.yaml` are loaded): a person reads them and moves the good ones into the bank, which is
published with the repository.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from norboten.questions import pipeline, providers
from norboten.quiz import bank


@dataclass
class Attempt:
    number: int
    accepted: bool
    question_id: str = ""
    prompt: str = ""
    stage: str = ""
    reason: str = ""


def prefix_of(topic: str, banks: list[bank.LoadedBank]) -> str:
    """The id prefix the topic's bank already uses (`net` for networking), else the topic's."""
    for loaded in banks:
        if loaded.bank.topic == topic and loaded.bank.questions:
            return loaded.bank.questions[0].id.rsplit("-", 1)[0]
    return re.sub(r"[^a-z0-9]", "", topic.lower())[:8] or "gen"


def draft(
    topic: str,
    out: Path,
    *,
    about: str | None = None,
    count: int = 5,
    difficulty: int = 2,
    generator: str = pipeline.DEFAULT_GENERATOR,
    verifiers: list[str] | None = None,
    min_verifiers: int = pipeline.DEFAULT_MIN_VERIFIERS,
    run_sandbox: bool = True,
    keep_unrun: bool = True,
    on_attempt: Callable[[Attempt], None] | None = None,
    banks: list[bank.LoadedBank] | None = None,
    config: providers.Config | None = None,
) -> list[Attempt]:
    """Attempt `count` questions and append the outcome to `out` after each one, so an interrupted
    run keeps what it had. Stops early when no verifier can be reached."""
    banks = bank.all_banks() if banks is None else banks
    drafted = yaml.safe_load(out.read_text()) if out.is_file() else None
    drafted = drafted or {"topic": topic, "accepted": [], "rejected": []}

    taken = {q.id for b in banks for q in b.bank.questions}
    taken |= {q["id"] for q in drafted["accepted"]}
    prompts = [q.prompt for b in banks for q in b.bank.questions]
    prompts += [q["prompt"] for q in drafted["accepted"]]
    prefix = prefix_of(topic, banks)

    attempts: list[Attempt] = []
    for n in range(1, count + 1):
        outcome = pipeline.generate(
            about or topic,
            difficulty=difficulty,
            existing_prompts=prompts,
            taken_ids=taken,
            id_prefix=prefix,
            generator_model=generator,
            verifier_models=verifiers or pipeline.DEFAULT_VERIFIERS,
            min_verifiers=min_verifiers,
            run_sandbox=run_sandbox,
            keep_unrun=keep_unrun,
            config=config,
        )
        prov = outcome.provenance
        if outcome.accepted and outcome.question is not None:
            question = outcome.question.model_dump(exclude_none=True, exclude_defaults=True)
            question = {"id": outcome.question.id, **question}
            question["provenance"] = {
                "generator": prov.generator,
                "solvers": prov.solvers,
                "critic": prov.critic,
                "execution": prov.execution,
                "date": date.today().isoformat(),
            }
            drafted["accepted"].append(question)
            taken.add(outcome.question.id)
            prompts.append(outcome.question.prompt)
            attempt = Attempt(n, True, outcome.question.id, outcome.question.prompt)
        else:
            reason = str(outcome.reason)[:300]
            drafted["rejected"].append({"stage": outcome.rejected_by, "reason": reason})
            attempt = Attempt(n, False, stage=outcome.rejected_by, reason=reason)
        attempts.append(attempt)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump(drafted, sort_keys=False, allow_unicode=True, width=100))
        if on_attempt:
            on_attempt(attempt)
        if outcome.rejected_by == "setup":
            break  # no verifier can be reached; every further attempt would say the same
    return attempts
