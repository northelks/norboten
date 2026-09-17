"""A learner's own questions: `g` on a Theory bank drafts more on its subject, on the learner's
Claude Code or keys, and what passes the pipeline becomes a practice bank of their own.

    ~/.norboten/quizzes/_drafts/<topic>.yaml   every attempt, with provenance and rejections
    ~/.norboten/quizzes/<topic>-yours.yaml     the accepted questions, as a bank

The bank is rebuilt from the drafts after each run, so the drafts file is the only record. These
questions never reach the server and never count towards a rating.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import yaml

from norboten.questions import drafts, pipeline, providers
from norboten.quiz import bank, verify

SUFFIX = "-yours"


def source_topic(loaded: bank.LoadedBank) -> str:
    return loaded.topic.removesuffix(SUFFIX) if loaded.own else loaded.topic


def drafts_path(topic: str) -> Path:
    return bank.own_dir() / "_drafts" / f"{topic}.yaml"


def bank_path(topic: str) -> Path:
    return bank.own_dir() / f"{topic}{SUFFIX}.yaml"


def rebuild(topic: str, source: bank.LoadedBank) -> Path | None:
    """Write the learner's bank for `topic` from the accepted drafts; None while there are none."""
    path = drafts_path(topic)
    drafted = yaml.safe_load(path.read_text()) if path.is_file() else None
    questions = [
        {k: v for k, v in q.items() if k != "provenance"}
        for q in (drafted or {}).get("accepted", [])
    ]
    if not questions:
        return None
    title = source.bank.title.removeprefix("Theory: ")
    data = {
        "schema_version": 1,
        "topic": f"{topic}{SUFFIX}",
        "topics": list(source.bank.topics),
        "title": f"Yours: {title}"[:60],
        "description": "Questions you drafted on your own Claude Code or keys. They passed the "
        "blind solve and the critic, but nobody else has read them. Practice only.",
        "questions": questions,
    }
    out = bank_path(topic)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100))
    bank.load(out, own=True)  # a bank that does not load is a bug here, not the learner's problem
    return out


def draft_more(
    source: bank.LoadedBank,
    *,
    count: int = 3,
    about: str | None = None,
    config: providers.Config | None = None,
    on_attempt: Callable[[drafts.Attempt], None] | None = None,
) -> list[drafts.Attempt]:
    config = config or providers.local_config(probe_ollama=True)
    models = pipeline.choose_models(config)
    if models is None:
        raise providers.NoProvider(
            "drafting needs Claude Code (claude on PATH, signed in), or keys or Ollama models for "
            "two models besides the writer (ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY)"
        )
    generator, solvers = models
    topic = source_topic(source)
    attempts = drafts.draft(
        topic,
        drafts_path(topic),
        about=about
        or f"{source.bank.title.removeprefix('Theory: ')} ({', '.join(source.bank.topics)})",
        count=count,
        generator=generator,
        verifiers=solvers,
        run_sandbox=verify.docker_available(),
        keep_unrun=False,
        on_attempt=on_attempt,
        banks=bank.all_banks() + bank.own_banks(),
        config=config,
    )
    rebuild(topic, source)
    return attempts
