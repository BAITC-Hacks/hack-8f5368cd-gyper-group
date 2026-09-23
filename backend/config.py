from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str = "llama-3.3-70b-versatile"
    llm_timeout_seconds: float = 0.45
    enable_tts: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
