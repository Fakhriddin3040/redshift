"""LLM integration. Nothing here knows a provider or a model by name:
the connection is described only by LLM_* environment variables."""

from vigil.llm.config import LLMSettings, get_llm_settings
from vigil.llm.provider import (
    LLMError,
    LLMProvider,
    OpenAICompatibleProvider,
    create_provider,
)

__all__ = [
    "LLMError",
    "LLMProvider",
    "LLMSettings",
    "OpenAICompatibleProvider",
    "create_provider",
    "get_llm_settings",
]
