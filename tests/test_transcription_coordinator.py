import wave
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.models.transcriptions import Transcription
from app.models.users import User
from app.models.voice_messages import VoiceMessage
from app.schemas.Transcription import TranscriptionResponse
from app.services.coordinator import TranscriptionCoordinator
from app.services.exceptions import (
    AudioTooLongException,
    FileTooLargeException,
    InvalidLanguageException,
    TranscriptionFailedException,
    UnsupportedFormatException,
)
from app.services.transcription import TranscriptionService


def _whisper_response(text: str = "Hello world", language: str = "english") -> MagicMock:
    return MagicMock(text=text, language=language)


def _synthesize_wav(duration_secs: float, sample_rate: int = 8000) -> bytes:
    """Return a valid mono 16-bit PCM WAV byte string of the given length."""
    n_frames = int(duration_secs * sample_rate)
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()


async def _make_user_in_session(session, **kwargs: str) -> User:
    user = User(
        username=kwargs.get("username", "alice"),
        email=kwargs.get("email", "alice@example.com"),
        password_hash="x" * 80,
    )
    session.add(user)
    await session.flush()
    return user


class _FakeUpload:
    def __init__(self, filename: str, content: bytes = b"fake-audio-bytes") -> None:
        self.filename = filename
        self._content = content

    async def read(self, _size: int = -1) -> bytes:
        return self._content


class _StubWhisperClient:
    def __init__(self, text: str = "Hello world", language: str = "english") -> None:
        self.audio = MagicMock()
        self.audio.transcriptions = MagicMock()
        self.audio.transcriptions.create = AsyncMock(
            return_value=_whisper_response(text=text, language=language)
        )
        self.calls = 0


async def test_valid_audio_persists_voice_message_and_transcription(db_session):
    user = await _make_user_in_session(db_session)
    await db_session.commit()

    whisper = _StubWhisperClient(text="Hello world", language="english")
    service = TranscriptionService(whisper_client=whisper)
    coordinator = TranscriptionCoordinator(db=db_session, transcription_service=service)

    upload = _FakeUpload("hello.mp3", b"x" * 1024)
    result = await coordinator.process_audio(
        user_id=user.id,
        file=upload,  # type: ignore[arg-type]
        language="auto",
        clean_enabled=False,
        snippets_enabled=True,
    )

    assert isinstance(result, TranscriptionResponse)
    assert result.success is True
    assert result.raw_text == "Hello world"
    assert result.detected_language == "english"
    assert result.audio_duration_secs == pytest.approx(0.0)
    assert result.latency_ms >= 0

    vm_rows = (await db_session.execute(select(VoiceMessage))).scalars().all()
    assert len(vm_rows) == 1
    vm = vm_rows[0]
    assert vm.user_id == user.id
    assert vm.filename == "hello.mp3"
    assert vm.language == "auto"
    assert vm.snippets_enabled is True
    assert vm.clean_enabled is False
    assert vm.file_size_bytes == len(b"x" * 1024)

    tx_rows = (await db_session.execute(select(Transcription))).scalars().all()
    assert len(tx_rows) == 1
    assert tx_rows[0].voice_message_id == vm.id
    assert tx_rows[0].raw_text == "Hello world"


async def test_unsupported_extension_raises(db_session):
    user = await _make_user_in_session(db_session)
    await db_session.commit()

    whisper = _StubWhisperClient()
    service = TranscriptionService(whisper_client=whisper)
    coordinator = TranscriptionCoordinator(db=db_session, transcription_service=service)

    upload = _FakeUpload("recording.txt", b"x" * 16)

    with pytest.raises(UnsupportedFormatException):
        await coordinator.process_audio(
            user_id=user.id,
            file=upload,  # type: ignore[arg-type]
            language="auto",
            clean_enabled=False,
            snippets_enabled=True,
        )


async def test_file_too_large_raises(db_session, monkeypatch):
    user = await _make_user_in_session(db_session)
    await db_session.commit()

    whisper = _StubWhisperClient()
    service = TranscriptionService(whisper_client=whisper)
    coordinator = TranscriptionCoordinator(db=db_session, transcription_service=service)

    # 1 MB file but limit set to 0 MB so any non-empty file fails
    monkeypatch.setattr(
        "app.services.transcription.settings.MAX_FILE_SIZE_MB", 0
    )

    upload = _FakeUpload("big.mp3", b"x" * (1024 * 1024))

    with pytest.raises(FileTooLargeException):
        await coordinator.process_audio(
            user_id=user.id,
            file=upload,  # type: ignore[arg-type]
            language="auto",
            clean_enabled=False,
            snippets_enabled=True,
        )


async def test_audio_too_long_raises(db_session, monkeypatch):
    user = await _make_user_in_session(db_session)
    await db_session.commit()

    whisper = _StubWhisperClient()
    service = TranscriptionService(whisper_client=whisper)
    coordinator = TranscriptionCoordinator(db=db_session, transcription_service=service)

    monkeypatch.setattr(
        "app.services.transcription.settings.MAX_AUDIO_DURATION_SECS", 1
    )

    upload = _FakeUpload("long.wav", _synthesize_wav(duration_secs=2.0))

    with pytest.raises(AudioTooLongException):
        await coordinator.process_audio(
            user_id=user.id,
            file=upload,  # type: ignore[arg-type]
            language="auto",
            clean_enabled=False,
            snippets_enabled=True,
        )


async def test_invalid_language_raises(db_session):
    user = await _make_user_in_session(db_session)
    await db_session.commit()

    whisper = _StubWhisperClient()
    service = TranscriptionService(whisper_client=whisper)
    coordinator = TranscriptionCoordinator(db=db_session, transcription_service=service)

    upload = _FakeUpload("clip.mp3", b"x" * 16)

    with pytest.raises(InvalidLanguageException):
        await coordinator.process_audio(
            user_id=user.id,
            file=upload,  # type: ignore[arg-type]
            language="not-a-real-code-123",
            clean_enabled=False,
            snippets_enabled=True,
        )


async def test_whisper_failure_raises_transcription_failed(db_session):
    user = await _make_user_in_session(db_session)
    await db_session.commit()

    failing_transcriptions = MagicMock()
    failing_transcriptions.create = AsyncMock(side_effect=RuntimeError("api down"))
    whisper = MagicMock()
    whisper.audio = MagicMock()
    whisper.audio.transcriptions = failing_transcriptions

    service = TranscriptionService(whisper_client=whisper)
    coordinator = TranscriptionCoordinator(db=db_session, transcription_service=service)

    upload = _FakeUpload("clip.mp3", b"x" * 16)

    with pytest.raises(TranscriptionFailedException):
        await coordinator.process_audio(
            user_id=user.id,
            file=upload,  # type: ignore[arg-type]
            language="auto",
            clean_enabled=False,
            snippets_enabled=True,
        )


def test_transcription_response_schema_fields():
    resp = TranscriptionResponse(
        raw_text="hi",
        detected_language="english",
        audio_duration_secs=1.5,
        latency_ms=42.0,
    )
    assert resp.success is True
    assert resp.raw_text == "hi"
    assert resp.detected_language == "english"
    assert resp.audio_duration_secs == 1.5
    assert resp.latency_ms == 42.0
