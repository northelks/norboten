"""Which model the tutor and the post-mortem use on this machine.

In order, the first that is here:

  1. Claude Code on the learner's subscription (`claude` on PATH): Sonnet unless they chose another
  2. the learner's own API key: ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY
  3. a local Ollama (OLLAMA_HOST, or one answering on its default port) with a model pulled

and with none of them, the lab's own hint ladder. The learner can pin one on System (`m`); the
choice is kept in ~/.norboten/settings.json as `tutor_model`, and `auto` means the order above.
"""

from __future__ import annotations

from dataclasses import dataclass

from norboten import settings
from norboten.questions import providers

AUTO = "auto"
CLAUDE_CODE = ["claude-code/sonnet", "claude-code/haiku", "claude-code/opus"]
KEYS = ["claude-sonnet-5", "gpt-5-codex", "gemini-3-pro"]
OLLAMA_PREFERRED = "ollama/qwen2.5:1.5b"

HOW_TO_GET_ONE = (
    "no model on this machine: install Claude Code and sign in, export ANTHROPIC_API_KEY, "
    "OPENAI_API_KEY or GEMINI_API_KEY, or run Ollama with a model pulled "
    f"(ollama pull {OLLAMA_PREFERRED.removeprefix('ollama/')})"
)


@dataclass(frozen=True)
class Choice:
    model: str
    source: str  # "Claude Code", "API key" or "Ollama"
    pinned: bool = False

    @property
    def label(self) -> str:
        return f"{self.model} ({self.source}{', chosen' if self.pinned else ''})"


def _source(model: str) -> str:
    vendor = providers.vendor_of(model)
    return {providers.CLAUDE_CODE: "Claude Code", providers.OLLAMA: "Ollama"}.get(vendor, "API key")


def available(config: providers.Config | None = None) -> list[Choice]:
    """Every model the tutor could use here, in the order `auto` tries them."""
    config = config or providers.local_config(probe_ollama=True)
    models = providers.usable_models([*CLAUDE_CODE, *KEYS], config)
    pulled = providers.ollama_models(config.ollama_url)
    pulled.sort(key=lambda m: m != OLLAMA_PREFERRED)
    return [Choice(m, _source(m)) for m in [*models, *pulled]]


def choose(config: providers.Config | None = None) -> Choice | None:
    """The model to ask now: the pinned one if it is still here, else the first in order."""
    options = available(config)
    pinned = str(settings.load().get("tutor_model") or AUTO)
    if pinned != AUTO:
        for option in options:
            if option.model == pinned:
                return Choice(option.model, option.source, pinned=True)
    return options[0] if options else None


def pin(model: str) -> None:
    settings.save(tutor_model=model)
