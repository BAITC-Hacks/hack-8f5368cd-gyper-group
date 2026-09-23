import os
from functools import lru_cache
from pathlib import Path

class Settings:
    """Runtime configuration loaded from environment variables or .env."""

    def __init__(self) -> None:
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.openai_stt_model = os.getenv("OPENAI_STT_MODEL", "whisper-1")
        self.openai_stt_fallback_model = os.getenv("OPENAI_STT_FALLBACK_MODEL", "whisper-1")
        self.openai_tts_model = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
        self.openai_tts_voice_ru = os.getenv("OPENAI_TTS_VOICE_RU", "marin")
        self.openai_tts_voice_kk = os.getenv("OPENAI_TTS_VOICE_KK", "cedar")
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        self.router_confidence_threshold = float(os.getenv("ROUTER_CONFIDENCE_THRESHOLD", "0.65"))
        self.data_dir = Path(os.getenv("DATA_DIR", "data"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
