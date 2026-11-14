from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VIGIL_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql://vigil:vigil@localhost:5432/vigil"
    vdev_url: str = "http://localhost:8100"
    ollama_url: str = ""
    pattern_model: str = "ml/models/pattern.json"
    actions_file: str = "docs/actions.yaml"
    cors_origin: str = "*"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_origin.split(",") if o.strip()] or ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
