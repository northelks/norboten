"""Claude through a local Claude Code: the question pipeline on a subscription, with no API key.

The unit tests stand a small script in for `claude` and read back the command it was given. The
last test runs the real `claude` (skipped where it is not installed) against the scripted Messages
API from automation/, through the whole pipeline and the drafting command — no token is spent.
"""

import json
import os
import shutil
import stat
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, Field

from norboten.questions import drafts, pipeline, providers

ROOT = Path(__file__).resolve().parents[2]


class Pick(BaseModel):
    label: str


def fake_claude(tmp_path: Path, body: dict, code: int = 0) -> Path:
    """A `claude` that records its arguments and working directory, then prints `body`."""
    script = tmp_path / "claude"
    log = tmp_path / "argv.json"
    script.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        f"open({str(log)!r}, 'w').write(json.dumps({{'argv': sys.argv[1:], 'cwd': os.getcwd()}}))\n"
        f"print({json.dumps(json.dumps(body))})\n"
        f"sys.exit({code})\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


@pytest.fixture
def claude_bin(monkeypatch, tmp_path):
    def use(body: dict, code: int = 0) -> Path:
        monkeypatch.setenv("NORBOTEN_CLAUDE_BIN", str(fake_claude(tmp_path, body, code)))
        return tmp_path / "argv.json"

    return use


def test_the_prefix_names_the_vendor():
    assert providers.vendor_of("claude-code/haiku") == providers.CLAUDE_CODE
    assert providers.vendor_of("claude-haiku-4-5-20251001") == providers.ANTHROPIC


def test_a_run_has_no_tools_no_project_and_the_schema(claude_bin):
    log = claude_bin({"is_error": False, "subtype": "success", "structured_output": {"label": "x"}})
    answer = providers.ask(model="claude-code/haiku", system="SYS", user="USER", schema=Pick)
    assert answer == Pick(label="x")

    ran = json.loads(log.read_text())
    argv = ran["argv"]
    assert argv[:2] == ["-p", "USER"]
    assert argv[argv.index("--model") + 1] == "haiku"
    assert argv[argv.index("--system-prompt") + 1] == "SYS"
    assert argv[argv.index("--tools") + 1] == ""
    assert json.loads(argv[argv.index("--json-schema") + 1])["required"] == ["label"]
    assert "--bare" not in argv, "bare mode would ignore the subscription token"
    assert "--max-turns" in argv
    assert not Path(ran["cwd"]).exists(), "an empty scratch directory, removed afterwards"
    assert ROOT.resolve() not in Path(ran["cwd"]).resolve().parents


def test_a_failed_run_is_a_provider_error(claude_bin):
    claude_bin({"is_error": True, "subtype": "error", "result": "Not logged in"}, code=1)
    with pytest.raises(providers.ProviderError, match="Not logged in"):
        providers.ask(model="claude-code/haiku", system="s", user="u", schema=Pick)


def test_an_answer_outside_the_schema_is_a_provider_error(claude_bin):
    claude_bin({"is_error": False, "structured_output": {"colour": "red"}})
    with pytest.raises(providers.ProviderError, match="does not fit the schema"):
        providers.ask(model="claude-code/haiku", system="s", user="u", schema=Pick)


def test_without_claude_on_path_the_model_is_not_usable(monkeypatch):
    monkeypatch.setenv("NORBOTEN_CLAUDE_BIN", "/nonexistent/claude")
    assert providers.usable_models(["claude-code/haiku"]) == []
    with pytest.raises(providers.NoProvider, match="not on PATH"):
        providers.provider_for("claude-code/haiku")


def test_a_caller_can_forbid_vendors():
    server = providers.Config(
        ollama_url="http://ollama:11434", anthropic_key="k", vendors=frozenset({providers.OLLAMA})
    )
    assert providers.usable_models(["claude-opus-5", "ollama/qwen2.5:0.5b"], server) == [
        "ollama/qwen2.5:0.5b"
    ]


def test_local_keys_come_from_the_standard_variables(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11434")
    config = providers.local_config()
    assert (config.anthropic_key, config.openai_key, config.gemini_key) == ("a", "o", "g")
    assert config.ollama_url == "http://127.0.0.1:11434"
    assert providers.usable_models(["claude-opus-5", "gpt-5-codex", "gemini-3-pro"]) == [
        "claude-opus-5",
        "gpt-5-codex",
        "gemini-3-pro",
    ]


class Nested(BaseModel):
    choices: list[Pick] = Field(min_length=3, max_length=6)
    difficulty: int = Field(ge=1, le=5)
    title: str = Field(max_length=10, default="x")


def test_the_messages_api_gets_a_schema_it_accepts_and_the_key(monkeypatch):
    sent = {}

    def post(self, url, payload, headers):
        sent.update(url=url, payload=payload, headers=headers)
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps({"label": "x"})}],
        }

    monkeypatch.setattr(providers.AnthropicProvider, "_post", post)
    config = providers.Config(anthropic_key="sk-test")
    answer = providers.ask(model="claude-opus-5", system="S", user="U", schema=Pick, config=config)
    assert answer == Pick(label="x")
    assert sent["url"] == "https://api.anthropic.com/v1/messages"
    assert sent["headers"] == {"x-api-key": "sk-test", "anthropic-version": "2023-06-01"}
    payload = sent["payload"]
    assert payload["system"] == "S" and payload["messages"] == [{"role": "user", "content": "U"}]
    fmt = payload["output_config"]["format"]
    assert fmt["type"] == "json_schema" and fmt["schema"]["additionalProperties"] is False

    schema = providers.structured_output_schema(Nested.model_json_schema())
    text = json.dumps(schema)
    for word in ("minItems", "maxItems", "minimum", "maximum", "maxLength"):
        assert word not in text
    assert "title" in schema["properties"], "a property named title is a property, not a keyword"
    assert schema["$defs"]["Pick"]["additionalProperties"] is False


def test_a_refusal_is_a_provider_error(monkeypatch):
    monkeypatch.setattr(
        providers.AnthropicProvider, "_post", lambda *a: {"stop_reason": "refusal", "content": []}
    )
    with pytest.raises(providers.ProviderError, match="declined"):
        providers.ask(
            model="claude-opus-5",
            system="s",
            user="u",
            schema=Pick,
            config=providers.Config(anthropic_key="k"),
        )


GOOD = {
    "type": "single",
    "difficulty": 2,
    "prompt": "Not in any bank yet: which tool lists open TCP sockets with their processes?",
    "choices": [
        {"id": "a", "text": "ss -tanp"},
        {"id": "b", "text": "ip route show"},
        {"id": "c", "text": "arp -n"},
        {"id": "d", "text": "uptime"},
    ],
    "answer": ["a"],
    "explanation": "ss -t selects TCP, -a all states, -p the process; the others show no sockets.",
    "references": ["man 8 ss"],
}


@pytest.mark.skipif(shutil.which("claude") is None, reason="Claude Code is not installed")
def test_the_pipeline_and_the_drafting_command_through_a_real_claude(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT))
    from automation.stand_ins import fake_anthropic

    server, script = fake_anthropic.serve(0)
    config = tmp_path / "config"
    config.mkdir()
    for name, value in {
        "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_address[1]}",
        "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat-test",
        "CLAUDE_CONFIG_DIR": str(config),
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_AUTOUPDATER": "1",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("NORBOTEN_CLAUDE_BIN", raising=False)
    # the draft reaches the solvers with its choices in the order its id fixes
    from norboten.quiz import bank as banks

    loaded = banks.all_banks()
    taken = {q.id for b in loaded for q in b.bank.questions}
    qid = pipeline._next_id(drafts.prefix_of("networking", loaded), taken)
    right = pipeline.to_question(pipeline.Draft.model_validate(GOOD), qid).answer
    solved = {"answer": right, "ambiguous": False, "note": ""}
    try:
        # generate, two blind solves, the critic: one structured answer each
        script.load(
            [
                {"tool": "StructuredOutput", "input": GOOD},
                {"tool": "StructuredOutput", "input": solved},
                {"tool": "StructuredOutput", "input": solved},
                {"tool": "StructuredOutput", "input": {"valid": True, "issues": []}},
            ]
        )
        out = tmp_path / "drafts.yaml"
        [attempt] = drafts.draft("networking", out, count=1)
        assert attempt.accepted
        drafted = yaml.safe_load(out.read_text())
        [question] = drafted["accepted"]
        assert question["id"].startswith("net-") and question["answer"] == right
        prov = question["provenance"]
        assert prov["generator"] == "claude-code/opus"
        assert [s["model"] for s in prov["solvers"]] == ["claude-code/sonnet", "claude-code/haiku"]
        assert prov["critic"] == {"model": "claude-code/sonnet", "valid": True, "issues": []}

        models = [r["model"] for r in script.requests]
        assert "opus" in models[0] and "sonnet" in models[1] and "haiku" in models[2]
        # the blind solvers never see the key, and no run is offered a tool but the answer
        for request in script.requests:
            assert request["tools"] == ["StructuredOutput"]
        for request in script.requests[1:3]:
            sent = json.dumps(request["messages"])
            assert "ss -tanp" in sent and "Key:" not in sent and GOOD["explanation"] not in sent
        assert "Key: a" in json.dumps(script.requests[3]["messages"])
        assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] and script.requests[0]["auth"] == "bearer"

        # the same question again is a duplicate of the draft, and the file keeps both records
        script.load(
            [
                {"tool": "StructuredOutput", "input": GOOD},
                {"tool": "StructuredOutput", "input": solved},
                {"tool": "StructuredOutput", "input": solved},
                {"tool": "StructuredOutput", "input": {"valid": True, "issues": []}},
            ]
        )
        [again] = drafts.draft("networking", out, count=1)
        assert not again.accepted
        drafted = yaml.safe_load(out.read_text())
        assert len(drafted["accepted"]) == 1
        assert [r["stage"] for r in drafted["rejected"]] == ["duplicate"]
    finally:
        server.shutdown()


def test_the_drafts_directory_is_not_a_bank():
    from norboten.quiz import bank

    assert all("_drafts" not in b.path.parts for b in bank.all_banks())
    assert pipeline.GENERATOR_SYSTEM
