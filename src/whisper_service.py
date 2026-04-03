import asyncio
import logging
from functools import lru_cache

from faster_whisper import WhisperModel

from config import WHISPER_MODEL, WHISPER_LANGUAGE

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_model() -> WhisperModel:
    logger.info("Loading Whisper model: %s", WHISPER_MODEL)
    return WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")


def _transcribe_sync(audio_path: str) -> str:
    model = _get_model()
    segments, info = model.transcribe(
        audio_path,
        language=WHISPER_LANGUAGE,
        beam_size=5,
    )
    logger.info(
        "Detected language: %s (probability %.2f)",
        info.language,
        info.language_probability,
    )
    text = " ".join(segment.text.strip() for segment in segments)
    return text.strip()


async def transcribe(audio_path: str) -> str:
    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(None, _transcribe_sync, audio_path)
    logger.info("Transcribed: %s", text[:100])
    return text
