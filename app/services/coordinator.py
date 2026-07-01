from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.transcriptions import Transcription
from app.models.voice_messages import VoiceMessage
from app.schemas.Transcription import TranscriptionResponse
from app.services.transcription import TranscriptionService


class _HasRead(Protocol):
    filename: str

    async def read(self, _size: int = -1) -> bytes: ...


class _InMemoryUpload:
    """A UploadFile-like wrapper that returns a pre-read byte buffer."""

    def __init__(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self._content = content

    async def read(self, _size: int = -1) -> bytes:
        return self._content

    @property
    def size(self) -> int:
        return len(self._content)


class TranscriptionCoordinator:
    """Orchestrates transcription + persistence. Issue 2 has no cleanup/snippets yet."""

    def __init__(
        self,
        db: AsyncSession,
        transcription_service: TranscriptionService,
    ) -> None:
        self.db = db
        self.transcription_service = transcription_service

    async def process_audio(
        self,
        user_id: int,
        file: _HasRead,
        language: str,
        clean_enabled: bool,
        snippets_enabled: bool,
    ) -> TranscriptionResponse:
        filename = file.filename or "audio"
        content = await file.read()
        file_size = len(content)

        result = await self.transcription_service.transcribe_audio(
            file=_InMemoryUpload(filename=filename, content=content),
            language=language,
        )

        voice_message = VoiceMessage(
            user_id=user_id,
            filename=filename,
            language=language or "auto",
            snippets_enabled=snippets_enabled,
            clean_enabled=clean_enabled,
            file_size_bytes=file_size,
            audio_duration_secs=result.duration_secs,
        )
        self.db.add(voice_message)
        await self.db.flush()

        transcription = Transcription(
            voice_message_id=voice_message.id,
            raw_text=result.text,
            detected_language=result.language,
            latency_ms=result.latency_ms,
            model=TranscriptionService.MODEL_NAME,
        )
        self.db.add(transcription)
        await self.db.commit()
        await self.db.refresh(transcription)

        return TranscriptionResponse(
            success=True,
            raw_text=result.text,
            detected_language=result.language,
            audio_duration_secs=result.duration_secs,
            latency_ms=result.latency_ms,
        )
