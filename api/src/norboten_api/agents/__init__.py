"""The server's one agent, the consultant, and the models it may use."""

from __future__ import annotations

from norboten.questions import providers
from norboten_api.settings import settings


def model_config() -> providers.Config:
    """The providers this server may use: its own Ollama, and nothing hosted."""
    return providers.Config(ollama_url=settings().ollama_url, vendors=frozenset({providers.OLLAMA}))
