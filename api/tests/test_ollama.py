"""The local model: Ollama's chat endpoint, and the consultant preferring it when it is there."""

import json

import pytest
from pydantic import BaseModel

from norboten.questions import providers
from norboten_api.agents import consultant, model_config
from norboten_api.settings import settings


class Reply(BaseModel):
    answer: str


@pytest.fixture
def ollama(monkeypatch):
    settings.cache_clear()
    monkeypatch.setenv("NORBOTEN_OLLAMA_URL", "http://ollama:11434/")
    monkeypatch.setenv("NORBOTEN_CONSULTANT_MODELS", "ollama/qwen2.5:0.5b")
    providers.register(providers.OLLAMA, providers.OllamaProvider())  # the real one, not the fake
    calls = []

    def post(self, url, payload, headers):
        calls.append((url, payload))
        return {"message": {"role": "assistant", "content": json.dumps({"answer": "from qwen"})}}

    monkeypatch.setattr(providers.OllamaProvider, "_post", post)
    yield calls
    settings.cache_clear()


def test_a_model_id_names_its_vendor():
    assert providers.vendor_of("ollama/qwen2.5:0.5b") == providers.OLLAMA
    assert providers.vendor_of("claude-haiku-4-5-20251001") == providers.ANTHROPIC


def test_ollama_gets_the_bare_name_and_the_schema(ollama):
    reply = providers.ask(
        model="ollama/qwen2.5:0.5b", system="s", user="u", schema=Reply, config=model_config()
    )
    assert reply.answer == "from qwen"
    url, payload = ollama[0]
    assert url == "http://ollama:11434/api/chat"
    assert payload["model"] == "qwen2.5:0.5b"
    assert payload["stream"] is False
    assert payload["format"]["properties"]["answer"]["type"] == "string"
    assert [m["role"] for m in payload["messages"]] == ["system", "user"]


def test_a_body_without_a_message_is_an_error(monkeypatch, ollama):
    monkeypatch.setattr(providers.OllamaProvider, "_post", lambda *a: {"error": "model not found"})
    with pytest.raises(providers.ProviderError, match="unexpected body"):
        providers.ask(
            model="ollama/qwen2.5:0.5b", system="s", user="u", schema=Reply, config=model_config()
        )


def test_no_ollama_url_means_no_ollama(monkeypatch):
    providers.register(providers.OLLAMA, providers.OllamaProvider())
    settings.cache_clear()
    monkeypatch.delenv("NORBOTEN_OLLAMA_URL", raising=False)
    try:
        with pytest.raises(providers.NoProvider):
            providers.provider_for("ollama/qwen2.5:0.5b", model_config())
    finally:
        settings.cache_clear()


def test_the_consultant_uses_the_local_model(ollama):
    assert consultant.pick_model() == "ollama/qwen2.5:0.5b"


def test_a_hosted_model_is_never_used_even_with_a_key_in_the_environment(monkeypatch, ollama):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-would-be-billed")
    monkeypatch.setenv("NORBOTEN_ANTHROPIC_API_KEY", "sk-would-be-billed")
    with pytest.raises(providers.NoProvider, match="not used here"):
        providers.provider_for("claude-opus-5", model_config())


def test_without_ollama_the_consultant_is_off(monkeypatch):
    providers.register(providers.OLLAMA, providers.OllamaProvider())
    settings.cache_clear()
    monkeypatch.delenv("NORBOTEN_OLLAMA_URL", raising=False)
    try:
        with pytest.raises(providers.NoProvider, match="no consultant model"):
            consultant.pick_model()
    finally:
        settings.cache_clear()
