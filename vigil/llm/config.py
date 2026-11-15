"""LLM connection settings. Every value comes from the environment (or .env):

    LLM_BASE_URL=https://api.example.com/v1
    LLM_API_KEY=your-api-key
    LLM_MODEL=model-name
    LLM_TIMEOUT=60
    LLM_MAX_RETRIES=3
    LLM_MAX_TOKENS=1000                    (optional)
    LLM_TEMPERATURE=0.2                    (optional)
    LLM_MAX_CALLS_PER_HOUR=30              (optional, 0 = no cap)
    LLM_EXTRA_BODY='{"key": "value"}'      (optional, provider-specific request fields)

Changing the provider or the model means changing these variables and nothing
else. With LLM_BASE_URL or LLM_MODEL empty the LLM is off and alert text comes
from templates.
"""

from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LLM_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout: float = 60.0  # seconds, per request
    max_retries: int = 3  # extra attempts after the first one
    temperature: float = 0.2
    # Room for the answer plus any hidden reasoning the model does first.
    max_tokens: int = 1000
    # Extra fields for the request body, as JSON. This is where provider-specific
    # switches go (for example turning a reasoning mode off), so the code needs none.
    extra_body: dict[str, Any] = {}
    # Spending cap: at most this many requests in any 60 minutes; further alerts
    # keep their template text. 0 = no cap.
    max_calls_per_hour: int = 30

    @property
    def enabled(self) -> bool:
        return bool(self.base_url.strip() and self.model.strip())


@lru_cache
def get_llm_settings() -> LLMSettings:
    return LLMSettings()
