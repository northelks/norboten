"""The verification pipeline has to reject broken questions — that is the whole point of it.

Every case here seeds a generator that produces a specific defect and asserts which stage catches
it, with the provenance a draft keeps.
"""

import pytest
from pydantic import BaseModel

from norboten.questions import pipeline, providers


class FakeProvider(providers.Provider):
    """A vendor whose answers the test decides: keyed by schema name, a value or a callable."""

    def __init__(self, name: str):
        self.name = name
        self.answers: dict[str, object] = {}

    def available(self, config) -> bool:
        return True

    def ask(self, *, model, system, user, schema, max_tokens, config):
        answer = self.answers.get(schema.__name__)
        if callable(answer):
            answer = answer(user=user)
        if answer is None:
            raise providers.ProviderError(f"no fake answer for {schema.__name__}")
        return answer if isinstance(answer, BaseModel) else schema.model_validate(answer)


@pytest.fixture
def fake_vendors():
    """Every vendor the pipeline is given is a fake; no test can reach a real model."""
    saved = dict(providers._PROVIDERS)
    fakes = {v: FakeProvider(v) for v in (providers.ANTHROPIC, providers.OPENAI, providers.GEMINI)}
    for vendor, fake in fakes.items():
        providers.register(vendor, fake)
    yield fakes
    providers._PROVIDERS.clear()
    providers._PROVIDERS.update(saved)


GOOD = {
    "type": "single",
    "difficulty": 2,
    "prompt": "Which command shows listening TCP sockets with the owning process?",
    "choices": [
        {"id": "a", "text": "ss -tlnp"},
        {"id": "b", "text": "ip route show"},
        {"id": "c", "text": "netstat -r"},
        {"id": "d", "text": "ip neigh"},
    ],
    "answer": ["a"],
    "explanation": "ss -t selects TCP, -l listening, -n no resolution, -p the owning process.",
    "references": ["man 8 ss"],
}

WRONG_KEY = {**GOOD, "answer": ["c"]}
TWO_CORRECT = {
    **GOOD,
    "prompt": "Which command can show listening TCP sockets?",
    "choices": [
        {"id": "a", "text": "ss -tln"},
        {"id": "b", "text": "netstat -tln"},
        {"id": "c", "text": "ip route show"},
        {"id": "d", "text": "uptime"},
    ],
    "answer": ["a"],
}
BANNED_CHOICE = {
    **GOOD,
    "choices": [*GOOD["choices"][:3], {"id": "d", "text": "All of the above"}],
}
NO_REFERENCE = {**GOOD, "references": []}
BAD_SNIPPET = {
    **GOOD,
    "prompt": "What does this print?",
    "code": 'x=5\nx+=1\necho "$x"',
    "code_lang": "bash",
    "choices": [
        {"id": "a", "text": "6"},
        {"id": "b", "text": "51"},
        {"id": "c", "text": "5"},
        {"id": "d", "text": "an error"},
    ],
    "answer": ["a"],  # wrong: bash appends, so it prints 51
    "verify": {"runtime": "bash", "code": 'x=5\nx+=1\necho "$x"'},
}


def _ids_for(draft, ids):
    """The draft's choices named by id, as texts: the pipeline shows them in another order."""
    texts = {c["id"]: c["text"] for c in draft["choices"]}
    return {texts[i] for i in ids}


def _wire(fakes, draft, *, solver_answer=None, ambiguous=False, critic_ok=True, issues=()):
    fakes["anthropic"].answers["Draft"] = draft
    wanted = _ids_for(draft, solver_answer if solver_answer is not None else draft["answer"])

    def solve(user, **_):
        # read the choices the way a model does, from "x) text" lines, and pick by text
        shown = [line.split(") ", 1) for line in user.splitlines() if line[1:3] == ") "]
        return {"answer": sorted(i for i, text in shown if text in wanted), "ambiguous": ambiguous}

    for vendor in ("openai", "gemini"):
        fakes[vendor].answers["SolveAnswer"] = solve
        fakes[vendor].answers["Critique"] = {"valid": critic_ok, "issues": list(issues)}


def _generate(**kw):
    return pipeline.generate(
        "networking",
        generator_model="claude-opus-5",
        verifier_models=["gpt-5-codex", "gemini-3-pro"],
        min_verifiers=2,
        **kw,
    )


def test_a_good_question_is_accepted_with_provenance(fake_vendors):
    _wire(fake_vendors, GOOD)
    out = _generate(run_sandbox=False)
    assert out.accepted
    assert out.question.id.startswith("networki-")
    assert [s["model"] for s in out.provenance.solvers] == ["gpt-5-codex", "gemini-3-pro"]
    assert all(s["agrees"] for s in out.provenance.solvers)
    assert out.provenance.critic["valid"] is True


def test_a_wrong_key_is_caught_by_the_blind_solvers(fake_vendors):
    # the solvers answer what is actually right; the key says otherwise
    _wire(fake_vendors, WRONG_KEY, solver_answer=["a"])
    out = _generate(run_sandbox=False)
    assert not out.accepted
    assert out.rejected_by == "blind_solve"
    assert "answered [" in out.reason


def test_an_ambiguous_question_is_rejected(fake_vendors):
    _wire(fake_vendors, TWO_CORRECT, ambiguous=True)
    out = _generate(run_sandbox=False)
    assert not out.accepted
    assert out.rejected_by == "blind_solve"
    assert "ambiguous" in out.reason


def test_the_critic_can_reject_what_the_solvers_agreed_on(fake_vendors):
    _wire(fake_vendors, GOOD, critic_ok=False, issues=["netstat -r is also plausible"])
    out = _generate(run_sandbox=False)
    assert not out.accepted
    assert out.rejected_by == "critic"
    assert "netstat" in out.reason


@pytest.mark.parametrize(
    ("draft", "why"), [(BANNED_CHOICE, "of the above"), (NO_REFERENCE, "references")]
)
def test_the_schema_stage_rejects_spec_violations(fake_vendors, draft, why):
    _wire(fake_vendors, draft)
    out = _generate(run_sandbox=False)
    assert not out.accepted
    assert out.rejected_by == "schema"
    assert why in str(out.reason)


def test_a_near_duplicate_is_rejected(fake_vendors):
    _wire(fake_vendors, GOOD)
    out = _generate(
        run_sandbox=False,
        existing_prompts=["Which command shows listening TCP sockets with the owning process?"],
    )
    assert not out.accepted
    assert out.rejected_by == "duplicate"


def test_verifiers_must_be_other_models(fake_vendors):
    _wire(fake_vendors, GOOD)
    out = pipeline.generate(
        "networking",
        generator_model="claude-opus-5",
        verifier_models=["claude-opus-5"],  # only the generator itself
        min_verifiers=2,
        run_sandbox=False,
    )
    assert not out.accepted
    assert out.rejected_by == "setup"


def test_ids_do_not_collide_with_existing_questions(fake_vendors):
    _wire(fake_vendors, GOOD)
    out = _generate(run_sandbox=False, taken_ids={"networki-001", "networki-002"})
    assert out.accepted
    assert out.question.id == "networki-003"


@pytest.mark.docker
def test_a_snippet_that_contradicts_the_key_is_caught_by_execution(fake_vendors):
    from norboten.quiz import verify as sandbox

    if not sandbox.docker_available():
        pytest.skip("docker is not available")
    _wire(fake_vendors, BAD_SNIPPET)
    out = _generate(run_sandbox=True)
    assert not out.accepted
    assert out.rejected_by == "execution"
    assert "'51'" in out.reason  # what bash actually printed
    assert out.provenance.execution["output"] == "51"


def test_a_snippet_nobody_ran_is_rejected_when_asked(fake_vendors):
    _wire(fake_vendors, BAD_SNIPPET)
    kept = _generate(run_sandbox=False)  # a maintainer reviews it, so it is kept
    assert kept.accepted
    out = _generate(run_sandbox=False, keep_unrun=False)
    assert not out.accepted and out.rejected_by == "execution" and "not run" in out.reason


@pytest.mark.parametrize(
    ("keys", "claude", "expected"),
    [
        ({}, True, ("claude-code/opus", ["claude-code/sonnet", "claude-code/haiku"])),
        ({"anthropic_key": "k"}, False, ("claude-opus-5", ["claude-sonnet-5", "claude-haiku-4-5"])),
        (
            {"anthropic_key": "k", "openai_key": "k"},
            False,
            ("claude-opus-5", ["claude-sonnet-5", "claude-haiku-4-5", "gpt-5-codex"]),
        ),
        ({"openai_key": "k", "gemini_key": "k"}, False, None),  # a writer and only one solver
        ({}, False, None),
    ],
)
def test_the_models_come_from_what_this_machine_has(keys, claude, expected):
    import sys

    config = providers.Config(claude_bin=sys.executable if claude else "/nonexistent", **keys)
    assert pipeline.choose_models(config) == expected


def test_ollama_models_come_last_as_they_do_for_the_tutor(monkeypatch):
    pulled = ["ollama/qwen2.5:1.5b", "ollama/llama3.2:3b", "ollama/gemma3:1b"]
    monkeypatch.setattr(providers, "ollama_models", lambda url, timeout=1.0: list(pulled))
    only_ollama = providers.Config(claude_bin="/nonexistent", ollama_url="http://127.0.0.1:11434")
    assert pipeline.choose_models(only_ollama) == (pulled[0], pulled[1:])
    with_a_key = providers.Config(
        claude_bin="/nonexistent", anthropic_key="k", ollama_url="http://127.0.0.1:11434"
    )
    generator, solvers = pipeline.choose_models(with_a_key)
    assert generator == "claude-opus-5"
    assert solvers == ["claude-sonnet-5", "claude-haiku-4-5", *pulled]


def test_own_questions_become_a_practice_bank(tmp_path, monkeypatch):
    import yaml

    from norboten.questions import drafts, own
    from norboten.quiz import bank

    monkeypatch.setenv("NORBOTEN_HOME", str(tmp_path))
    monkeypatch.setattr(pipeline, "choose_models", lambda config=None: ("w", ["s1", "s2"]))
    monkeypatch.setattr(own.verify, "docker_available", lambda: False)
    source = bank.find_topic("networking")
    seen = {}

    def fake_draft(topic, out, **kw):
        seen.update(kw, topic=topic)
        question = {**GOOD, "id": "net-900", "provenance": {"generator": "w"}}
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.safe_dump({"topic": topic, "accepted": [question], "rejected": []}))
        return [drafts.Attempt(1, True, "net-900", GOOD["prompt"])]

    monkeypatch.setattr(drafts, "draft", fake_draft)
    [attempt] = own.draft_more(source, count=1)
    assert attempt.accepted
    assert seen["topic"] == "networking" and seen["keep_unrun"] is False
    assert seen["generator"] == "w" and seen["verifiers"] == ["s1", "s2"]

    [mine] = bank.own_banks()
    assert mine.own and mine.topic == "networking-yours"
    assert [q.id for q in mine.bank.questions] == ["net-900"]
    assert "provenance" not in mine.path.read_text()
    assert own.source_topic(mine) == "networking"
    assert all(not b.own for b in bank.all_banks()), "published banks never include your own"


def test_drafting_without_models_says_what_is_needed(monkeypatch):
    from norboten.questions import own
    from norboten.quiz import bank

    monkeypatch.setattr(pipeline, "choose_models", lambda config=None: None)
    with pytest.raises(providers.NoProvider, match="Claude Code"):
        own.draft_more(bank.find_topic("networking"))


def test_a_drafted_question_does_not_keep_its_answer_first(fake_vendors):
    _wire(fake_vendors, GOOD)
    out = _generate(run_sandbox=False)
    assert out.accepted
    # the order is fixed by the id, and the answer follows its text wherever it lands
    assert out.question.choice_text(out.question.answer[0]) == "ss -tlnp"
    again = pipeline.to_question(pipeline.Draft.model_validate(GOOD), out.question.id)
    assert [c.text for c in again.choices] == [c.text for c in out.question.choices]
