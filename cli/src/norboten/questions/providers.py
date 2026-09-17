"""Model providers behind one small interface: a system prompt, a user prompt, a schema.

Claude is reached through the local Claude Code on a subscription (`claude-code/<model>`), which is
the default everywhere a question is drafted, or through the Messages API with your own key. OpenAI,
Gemini and Ollama go through their documented REST endpoints with httpx: one JSON call each, and no
vendor SDK in the package a learner installs.

Which providers exist depends on a `Config`: `local_config()` reads the standard environment
variables of a laptop (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OLLAMA_HOST`); the
API server builds its own from its settings and allows Ollama alone.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

ANTHROPIC = "anthropic"
OPENAI = "openai"
GEMINI = "gemini"
OLLAMA = "ollama"
CLAUDE_CODE = "claude-code"


class ProviderError(RuntimeError):
    pass


class NoProvider(ProviderError):
    """No key, binary or server for the requested model's vendor."""


@dataclass(frozen=True)
class Config:
    anthropic_key: str = ""
    openai_key: str = ""
    gemini_key: str = ""
    ollama_url: str = ""
    claude_bin: str = "claude"
    #: The vendors this caller may use at all; None allows every one.
    vendors: frozenset[str] | None = None


OLLAMA_DEFAULT_URL = "http://127.0.0.1:11434"


def ollama_models(url: str, timeout: float = 1.0) -> list[str]:
    """Models an Ollama at `url` has pulled, as `ollama/<name>` ids; [] if it does not answer."""
    if not url:
        return []
    try:
        r = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=timeout)
        r.raise_for_status()
        return [f"ollama/{m['name']}" for m in r.json().get("models", []) if m.get("name")]
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        return []


def local_config(probe_ollama: bool = False) -> Config:
    """A laptop's providers: Claude Code if it is installed, whatever keys are exported, and Ollama
    at OLLAMA_HOST — or, with `probe_ollama`, at its default address when one answers there."""
    ollama = os.environ.get("OLLAMA_HOST", "")
    if ollama and "://" not in ollama:
        ollama = f"http://{ollama}"
    if not ollama and probe_ollama and ollama_models(OLLAMA_DEFAULT_URL, timeout=0.5):
        ollama = OLLAMA_DEFAULT_URL
    return Config(
        anthropic_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        openai_key=os.environ.get("OPENAI_API_KEY", ""),
        gemini_key=os.environ.get("GEMINI_API_KEY", ""),
        ollama_url=ollama,
        claude_bin=os.environ.get("NORBOTEN_CLAUDE_BIN", "claude"),
    )


def vendor_of(model: str) -> str:
    if model.startswith("ollama/"):
        return OLLAMA
    if model.startswith("claude-code/"):
        return CLAUDE_CODE
    if model.startswith("claude"):
        return ANTHROPIC
    if model.startswith(("gpt", "o1", "o3", "o4", "codex")):
        return OPENAI
    if model.startswith("gemini"):
        return GEMINI
    raise ProviderError(f"cannot tell which vendor serves {model!r}")


class Provider:
    """One vendor's JSON-returning completion call."""

    name = "provider"

    def available(self, config: Config) -> bool:
        raise NotImplementedError

    def missing(self, config: Config) -> str:
        return f"no API key for {self.name}"

    def ask(
        self,
        *,
        model: str,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int,
        config: Config,
    ) -> T:
        raise NotImplementedError


class _RestProvider(Provider):
    timeout = 120.0

    def _post(self, url: str, payload: dict, headers: dict) -> dict:
        with httpx.Client(timeout=self.timeout) as http:
            r = http.post(url, json=payload, headers=headers)
        if r.status_code >= 400:
            raise ProviderError(f"{self.name} returned HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    @staticmethod
    def _validate(text: str, schema: type[T], model: str) -> T:
        try:
            return schema.model_validate_json(text)
        except ValidationError as e:
            raise ProviderError(f"{model} returned JSON that does not fit the schema: {e}") from e


#: JSON Schema keywords the Messages API's structured outputs do not accept; the answer is still
#: validated against the full Pydantic model afterwards, so dropping them loses no check.
_UNSUPPORTED = frozenset(
    {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"}
    | {"minLength", "maxLength", "minItems", "maxItems", "pattern", "default", "title"}
)


def structured_output_schema(schema: dict) -> dict:
    """A Pydantic JSON Schema narrowed to what `output_config.format` accepts: no numeric, string
    or array constraints, and `additionalProperties: false` on every object."""

    def walk(node: object) -> object:
        if isinstance(node, list):
            return [walk(item) for item in node]
        if not isinstance(node, dict):
            return node
        out = {}
        for key, value in node.items():
            if key in _UNSUPPORTED and not isinstance(value, dict):
                continue
            # "properties" maps names to schemas: a property may be called "default" or "title"
            out[key] = (
                {k: walk(v) for k, v in value.items()} if key == "properties" else walk(value)
            )
        if out.get("type") == "object" or "properties" in out:
            out["additionalProperties"] = False
        return out

    return walk(schema)  # type: ignore[return-value]


class AnthropicProvider(_RestProvider):
    name = ANTHROPIC
    url = "https://api.anthropic.com/v1/messages"

    def available(self, config: Config) -> bool:
        return bool(config.anthropic_key)

    def ask(self, *, model, system, user, schema, max_tokens, config):
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": structured_output_schema(schema.model_json_schema()),
                }
            },
        }
        headers = {"x-api-key": config.anthropic_key, "anthropic-version": "2023-06-01"}
        body = self._post(self.url, payload, headers)
        if body.get("stop_reason") == "refusal":
            raise ProviderError(f"{model} declined to answer")
        text = next(
            (b.get("text", "") for b in body.get("content", []) if b.get("type") == "text"), None
        )
        if text is None:
            raise ProviderError(f"{model} returned no text: {json.dumps(body)[:300]}")
        return self._validate(text, schema, model)


class OpenAIProvider(_RestProvider):
    name = OPENAI
    url = "https://api.openai.com/v1/chat/completions"

    def available(self, config: Config) -> bool:
        return bool(config.openai_key)

    def ask(self, *, model, system, user, schema, max_tokens, config):
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__.lower(),
                    "schema": schema.model_json_schema(),
                    "strict": False,
                },
            },
        }
        body = self._post(self.url, payload, {"Authorization": f"Bearer {config.openai_key}"})
        return self._validate(body["choices"][0]["message"]["content"], schema, model)


class GeminiProvider(_RestProvider):
    name = GEMINI
    url = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def available(self, config: Config) -> bool:
        return bool(config.gemini_key)

    def ask(self, *, model, system, user, schema, max_tokens, config):
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "maxOutputTokens": max_tokens,
            },
        }
        body = self._post(
            self.url.format(model=model), payload, {"x-goog-api-key": config.gemini_key}
        )
        try:
            text = body["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise ProviderError(
                f"{model} returned an unexpected body: {json.dumps(body)[:300]}"
            ) from e
        return self._validate(text, schema, model)


class OllamaProvider(_RestProvider):
    """A model through Ollama's chat endpoint. Model ids are `ollama/<name>`, for example
    `ollama/qwen2.5:0.5b`. The JSON schema goes in `format`, which Ollama enforces while decoding —
    a small model cannot wander out of the shape it was asked for."""

    name = OLLAMA
    timeout = 180.0  # a CPU-only box answers slowly, and that is still an answer

    def available(self, config: Config) -> bool:
        return bool(config.ollama_url)

    def missing(self, config: Config) -> str:
        return "no Ollama configured"

    def ask(self, *, model, system, user, schema, max_tokens, config):
        payload = {
            "model": model.removeprefix("ollama/"),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": schema.model_json_schema(),
            "options": {"num_predict": max_tokens, "temperature": 0.2},
        }
        body = self._post(f"{config.ollama_url.rstrip('/')}/api/chat", payload, {})
        try:
            text = body["message"]["content"]
        except (KeyError, TypeError) as e:
            raise ProviderError(
                f"{model} returned an unexpected body: {json.dumps(body)[:300]}"
            ) from e
        return self._validate(text, schema, model)


class ClaudeCodeProvider(Provider):
    """Claude through the `claude` binary on this machine: one headless run per call.

    Model ids are `claude-code/<alias or id>`, for example `claude-code/haiku`. The run gets the
    system prompt in place of Claude Code's own (`--system-prompt`), **no tools** (`--tools ""`),
    an empty working directory (so no project CLAUDE.md, hooks or MCP servers load) and the schema
    as `--json-schema`; the answer is `structured_output`. Authentication is whatever that Claude
    Code already has — a `/login`, or `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` — so
    questions are drafted on a subscription with no API key. Never `--bare`: bare mode ignores
    subscription credentials. Claude Code has no output-token cap; `max_tokens` is not passed.
    """

    name = CLAUDE_CODE
    timeout = 300
    max_turns = 3  # the structured answer is a tool call, and the run needs a turn to finish

    def available(self, config: Config) -> bool:
        return shutil.which(config.claude_bin) is not None

    def missing(self, config: Config) -> str:
        return f"{config.claude_bin!r} is not on PATH"

    def ask(self, *, model, system, user, schema, max_tokens, config):
        cmd = [
            config.claude_bin,
            "-p",
            user,
            "--model",
            model.removeprefix("claude-code/"),
            "--system-prompt",
            system,
            "--tools",
            "",
            "--json-schema",
            json.dumps(schema.model_json_schema()),
            "--output-format",
            "json",
            "--max-turns",
            str(self.max_turns),
            "--no-session-persistence",
        ]
        with tempfile.TemporaryDirectory(prefix="norboten-claude-") as empty:
            try:
                done = subprocess.run(
                    cmd, input="", capture_output=True, text=True, cwd=empty, timeout=self.timeout
                )
            except subprocess.TimeoutExpired as e:
                raise ProviderError(f"{model} did not answer in {self.timeout} s") from e
        try:
            body = json.loads(done.stdout)
        except json.JSONDecodeError:
            raise ProviderError(
                f"{model}: claude exited {done.returncode} without a JSON result: "
                f"{(done.stderr or done.stdout)[-300:]}"
            ) from None
        if body.get("is_error") or done.returncode != 0:
            detail = body.get("errors") or body.get("result") or body.get("subtype")
            raise ProviderError(f"{model}: the claude run failed: {str(detail)[:300]}")
        answer = body.get("structured_output")
        if answer is None:
            raise ProviderError(f"{model} returned no structured output")
        return _RestProvider._validate(json.dumps(answer), schema, model)


_PROVIDERS: dict[str, Provider] = {
    ANTHROPIC: AnthropicProvider(),
    OPENAI: OpenAIProvider(),
    GEMINI: GeminiProvider(),
    OLLAMA: OllamaProvider(),
    CLAUDE_CODE: ClaudeCodeProvider(),
}


def register(vendor: str, provider: Provider) -> None:
    """Used by the tests to plug in a fake vendor."""
    _PROVIDERS[vendor] = provider


def provider_for(model: str, config: Config | None = None) -> Provider:
    config = config or local_config()
    vendor = vendor_of(model)
    if config.vendors is not None and vendor not in config.vendors:
        raise NoProvider(f"{vendor} models are not used here")
    provider = _PROVIDERS[vendor]
    if not provider.available(config):
        raise NoProvider(provider.missing(config))
    return provider


def ask[M: BaseModel](
    *,
    model: str,
    system: str,
    user: str,
    schema: type[M],
    max_tokens: int = 4000,
    config: Config | None = None,
) -> M:
    config = config or local_config()
    return provider_for(model, config).ask(
        model=model, system=system, user=user, schema=schema, max_tokens=max_tokens, config=config
    )


def usable_models(models: list[str], config: Config | None = None) -> list[str]:
    """The subset of models this config can actually reach."""
    config = config or local_config()
    out = []
    for m in models:
        try:
            provider_for(m, config)
        except (ProviderError, KeyError):
            continue
        out.append(m)
    return out
