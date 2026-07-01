import os
import time
from io import BytesIO
from typing import Protocol

from mutagen import File as MutagenFile

from app.core.config import settings
from app.schemas.Transcription import TranscriptionResult
from app.services.exceptions import (
    AudioTooLongException,
    FileTooLargeException,
    InvalidLanguageException,
    TranscriptionFailedException,
    UnsupportedFormatException,
)


class _HasRead(Protocol):
    filename: str

    async def read(self, _size: int = -1) -> bytes: ...


_ISO_639_1_CODES: set[str] = {
    "aa", "ab", "ae", "af", "ak", "am", "an", "ar", "as", "av", "ay", "az",
    "ba", "be", "bg", "bh", "bi", "bm", "bn", "bo", "br", "bs", "ca", "ce",
    "ch", "co", "cr", "cs", "cu", "cv", "cy", "da", "de", "dv", "dz", "ee",
    "el", "en", "eo", "es", "et", "eu", "fa", "ff", "fi", "fj", "fo", "fr",
    "fy", "ga", "gd", "gl", "gn", "gu", "gv", "ha", "he", "hi", "ho", "hr",
    "ht", "hu", "hy", "hz", "ia", "id", "ie", "ig", "ii", "ik", "io", "is",
    "it", "iu", "ja", "jv", "ka", "kg", "ki", "kj", "kk", "kl", "km", "kn",
    "ko", "kr", "ks", "ku", "kv", "kw", "ky", "la", "lb", "lg", "li", "ln",
    "lo", "lt", "lu", "lv", "mg", "mh", "mi", "mk", "ml", "mn", "mr", "ms",
    "mt", "my", "na", "nb", "nd", "ne", "ng", "nl", "nn", "no", "nr", "nv",
    "ny", "oc", "oj", "om", "or", "os", "pa", "pi", "pl", "ps", "pt", "qu",
    "rm", "rn", "ro", "ru", "rw", "sa", "sc", "sd", "se", "sg", "si", "sk",
    "sl", "sm", "sn", "so", "sq", "sr", "ss", "st", "su", "sv", "sw", "ta",
    "te", "tg", "th", "ti", "tk", "tl", "tn", "to", "tr", "ts", "tt", "tw",
    "ty", "ug", "uk", "ur", "uz", "ve", "vi", "vo", "wa", "wo", "xh", "yi",
    "yo", "za", "zh", "zu",
}


class TranscriptionService:
    """Validates audio and calls the Whisper API. No DB access."""

    MODEL_NAME = "whisper-1"

    def __init__(self, whisper_client: object) -> None:
        self._whisper = whisper_client

    @staticmethod
    def _extension(filename: str) -> str:
        _, ext = os.path.splitext(filename or "")
        return ext.lower()

    @classmethod
    def _validate_extension(cls, filename: str) -> str:
        ext = cls._extension(filename)
        if ext not in settings.ALLOWED_EXTENSIONS:
            raise UnsupportedFormatException(
                f"Unsupported file extension: {ext!r}"
            )
        return ext

    @staticmethod
    def _validate_size(file_size_bytes: int) -> None:
        max_bytes = settings.MAX_FILE_SIZE_MB * 1024 * 1024
        if file_size_bytes > max_bytes:
            raise FileTooLargeException(
                f"File size {file_size_bytes} exceeds limit {max_bytes}"
            )

    @staticmethod
    def _validate_language(language: str) -> str:
        if language is None:
            raise InvalidLanguageException("Language code is required")
        code = language.strip().lower()
        if code != "auto" and code not in _ISO_639_1_CODES:
            raise InvalidLanguageException(f"Invalid language code: {language!r}")
        return code

    @staticmethod
    def _duration_from_mutagen(content: bytes) -> float:
        if not content:
            return 0.0
        try:
            audio = MutagenFile(BytesIO(content))
        except Exception:
            return 0.0
        if audio is None or audio.info is None:
            return 0.0
        duration = getattr(audio.info, "length", None)
        if not duration or duration <= 0:
            return 0.0
        return float(duration)

    def _validate_duration(self, content: bytes) -> float:
        duration = self._duration_from_mutagen(content)
        if duration > settings.MAX_AUDIO_DURATION_SECS:
            raise AudioTooLongException(
                f"Audio duration {duration}s exceeds limit "
                f"{settings.MAX_AUDIO_DURATION_SECS}s"
            )
        return duration

    async def transcribe_audio(
        self,
        file: _HasRead,
        language: str,
    ) -> TranscriptionResult:
        ext = self._validate_extension(file.filename)
        content = await file.read()
        self._validate_size(len(content))
        duration = self._validate_duration(content)
        normalized_lang = self._validate_language(language)

        request_language: str | None = None
        if normalized_lang != "auto":
            request_language = normalized_lang

        start = time.perf_counter()
        try:
            response = await self._whisper.audio.transcriptions.create(  # type: ignore[attr-defined]
                model=self.MODEL_NAME,
                file=(file.filename or f"audio{ext}", content),
                response_format="verbose_json",
                **({"language": request_language} if request_language else {}),
            )
        except Exception as exc:  # noqa: BLE001
            raise TranscriptionFailedException(str(exc)) from exc
        latency_ms = (time.perf_counter() - start) * 1000.0

        text = getattr(response, "text", "") or ""
        detected_language = getattr(response, "language", None)

        return TranscriptionResult(
            text=text,
            language=detected_language,
            duration_secs=duration,
            latency_ms=latency_ms,
        )
