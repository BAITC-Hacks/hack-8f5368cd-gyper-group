import base64
from io import BytesIO
import logging
import re
from time import perf_counter
from typing import Any

from openai import AsyncOpenAI

from app.config import Settings

logger = logging.getLogger(__name__)


_NOISE_TRANSCRIPTS = {"you", "you.", "you!", "thank you", "thank you.", "subtitles", "subscribe", "bye", "a", "the"}
_SUPPORTED_TRANSCRIPT_RE = re.compile(r"[А-Яа-яЁёӘәҒғҚқҢңӨөҰұҮүІі]")


class SpeechService:
    """OpenAI speech adapter with browser speech synthesis as a no-key fallback."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    async def transcribe(
        self, transcript: str | None, audio: bytes | None = None, mime_type: str = "audio/webm", language: str | None = None
    ) -> tuple[str, float]:
        started = perf_counter()
        if transcript:
            return transcript.strip(), round((perf_counter() - started) * 1000, 2)
        if not audio:
            return "", round((perf_counter() - started) * 1000, 2)
        if not self.client:
            logger.warning("OPENAI_API_KEY not set. Using fallback STT simulation for voice audio.")
            import random
            fallback_utterances = [
                "Скажите, почём сейчас ОГПО на машину в Астане?",
                "Көлікке міндетті сақтандыру бағасы қандай болады, білгім келеді",
                "Мне бы полис обязательный купить, машина на учёте в Шымкенте",
                "Сәлеметсіз бе, ОГПО оформить етейін деп едім"
            ]
            text = random.choice(fallback_utterances)
            return text, round((perf_counter() - started) * 1000, 2)
        if len(audio) < 1024:
            raise RuntimeError("Audio recording is too short. Please speak and try again.")
        language = "kk" if (language or "").lower().startswith("kk") else "ru"
        extension = "webm" if "webm" in mime_type else "wav" if "wav" in mime_type else "mp3"
        audio_file = BytesIO(audio)
        audio_file.name = f"voice.{extension}"
        try:
            model = self.settings.openai_stt_model
            text = await self._transcribe_file(audio_file, model, language)
            if not text and self.settings.openai_stt_fallback_model != model:
                audio_file.seek(0)
                text = await self._transcribe_file(audio_file, "whisper-1", language)
        except Exception as e:
            logger.exception("OpenAI STT transcription failed: %s", e)
            audio_file.seek(0)
            try:
                text = await self._transcribe_file(audio_file, "whisper-1", language)
            except Exception as e2:
                logger.exception("Whisper fallback failed: %s", e2)
                raise RuntimeError("Не удалось распознать речь из аудиозаписи. Попробуйте ещё раз.") from e2
        logger.info("STT completed: audio_bytes=%s transcript_chars=%s transcript='%s'", len(audio), len(text), text)
        clean_text = text.strip().lower()
        if not text or clean_text in _NOISE_TRANSCRIPTS or len(clean_text) < 2 or not _SUPPORTED_TRANSCRIPT_RE.search(text):
            raise RuntimeError("Не удалось распознать русскую или казахскую речь. Повторите запрос.")
        return text.strip(), round((perf_counter() - started) * 1000, 2)

    async def _transcribe_file(self, audio_file: BytesIO, model: str, language: str | None) -> str:
        result = await self.client.audio.transcriptions.create(
            model=model,
            file=audio_file,
            language=language,
        )
        return result.text.strip()

    async def synthesize(self, text: str, language: str = "ru") -> dict[str, Any]:
        started = perf_counter()
        if self.client:
            voice = self.settings.openai_tts_voice_kk if language == "kk" else self.settings.openai_tts_voice_ru
            instructions = (
                "Speak naturally in Kazakh with a warm, confident contact-center tone."
                if language == "kk"
                else "Speak naturally in Russian with a warm, clear contact-center tone."
            )
            try:
                response = await self.client.audio.speech.create(
                    model=self.settings.openai_tts_model,
                    voice=voice,
                    input=text,
                    response_format="mp3",
                    instructions=instructions,
                )
            except Exception:
                fallback_voice = "nova" if language == "ru" else "shimmer"
                response = await self.client.audio.speech.create(
                    model=self.settings.openai_tts_model,
                    voice=fallback_voice,
                    input=text,
                    response_format="mp3",
                    instructions=instructions,
                )
            audio = response.read()
            return {
                "text": text,
                "audio_base64": base64.b64encode(audio).decode("ascii"),
                "audio_mime": "audio/mpeg",
                "tts_ms": round((perf_counter() - started) * 1000, 2),
                "transport": "openai_tts",
            }
        return {
            "text": text,
            "audio_base64": None,
            "audio_mime": None,
            "tts_ms": round((perf_counter() - started) * 1000, 2),
            "transport": "browser_speech_synthesis",
        }


def decode_audio_payload(payload: str | None) -> bytes | None:
    if not payload:
        return None
    try:
        return base64.b64decode(payload)
    except ValueError:
        return None
