import asyncio
import base64
import time

from config import Settings


class TTSService:
    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.enable_tts

    async def synthesize(self, text: str, language: str) -> tuple[str | None, float]:
        started = time.perf_counter()
        if not self.enabled:
            return None, (time.perf_counter() - started) * 1000
        try:
            import edge_tts
            voice = "kk-KZ-AigulNeural" if language == "kk" else "ru-RU-SvetlanaNeural"
            communicator = edge_tts.Communicate(text, voice)
            audio = b"".join([chunk["data"] async for chunk in communicator.stream() if chunk["type"] == "audio"])
            return base64.b64encode(audio).decode("ascii"), (time.perf_counter() - started) * 1000
        except Exception:
            return None, (time.perf_counter() - started) * 1000
