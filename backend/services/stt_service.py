import time


class STTService:
    async def transcribe(self, audio: bytes, mime_type: str | None = None) -> tuple[str, float]:
        """Integration point for Faster-Whisper, Deepgram, or SpeechKit.

        Audio recognition needs a configured provider; the UI keeps text input usable
        so the complete router can be demonstrated without a cloud speech credential.
        """
        started = time.perf_counter()
        _ = (audio, mime_type)
        elapsed = (time.perf_counter() - started) * 1000
        return "", elapsed
