import wave
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.models.cleanup_snippets import CleanupSnippet
from app.models.cleanups import Cleanup
from app.models.snippets import Snippet
from app.models.transcription_snippets import TranscriptionSnippet
from app.models.transcriptions import Transcription
from app.models.users import User
from app.models.voice_messages import VoiceMessage
from app.schemas.Transcription import TranscriptionResponse
from app.services.cleanup import CleanupService
from app.services.coordinator import TranscriptionCoordinator
from app.services.exceptions import (
    AudioTooLongException,
    FileTooLargeException,
    InvalidLanguageException,
    TranscriptionFailedException,
    UnsupportedFormatException,
)
from app.services.snippets import SnippetService
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


class _StubCleanupService(CleanupService):
    """CleanupService subclass that returns a scripted output for testing."""

    def __init__(self, cleaned_text: str, model: str = "test-cleanup-model") -> None:
        super().__init__(model=model)
        self._scripted = cleaned_text
        self.calls: list[str] = []

    async def _run_agent(self, text: str) -> str:
        self.calls.append(text)
        return self._scripted


def _build_coordinator(
    db_session: Any,
    *,
    whisper_text: str = "Hello world",
    whisper_language: str = "english",
    cleaned_text: str | None = None,
) -> tuple[TranscriptionCoordinator, _StubWhisperClient, _StubCleanupService]:
    whisper = _StubWhisperClient(text=whisper_text, language=whisper_language)
    service = TranscriptionService(whisper_client=whisper)
    snippet_service = SnippetService(db=db_session)
    cleanup_service = _StubCleanupService(
        cleaned_text=cleaned_text if cleaned_text is not None else whisper_text
    )
    coordinator = TranscriptionCoordinator(
        db=db_session,
        transcription_service=service,
        snippet_service=snippet_service,
        cleanup_service=cleanup_service,
    )
    return coordinator, whisper, cleanup_service


async def test_valid_audio_persists_voice_message_and_transcription(db_session):
    user = await _make_user_in_session(db_session)
    await db_session.commit()

    coordinator, _, _ = _build_coordinator(db_session)

    upload = _FakeUpload("hello.mp3", b"x" * 1024)
    result = await coordinator.process_audio(
        user_id=user.id,
        file=upload,  # type: ignore[arg-type]
        language="auto",
        clean_enabled=False,
        snippets_enabled=False,
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
    assert vm.snippets_enabled is False
    assert vm.clean_enabled is False
    assert vm.file_size_bytes == len(b"x" * 1024)

    tx_rows = (await db_session.execute(select(Transcription))).scalars().all()
    assert len(tx_rows) == 1
    assert tx_rows[0].voice_message_id == vm.id
    assert tx_rows[0].raw_text == "Hello world"

    cleanup_rows = (await db_session.execute(select(Cleanup))).scalars().all()
    assert cleanup_rows == []


async def test_unsupported_extension_raises(db_session):
    user = await _make_user_in_session(db_session)
    await db_session.commit()

    coordinator, _, _ = _build_coordinator(db_session)

    upload = _FakeUpload("recording.txt", b"x" * 16)

    with pytest.raises(UnsupportedFormatException):
        await coordinator.process_audio(
            user_id=user.id,
            file=upload,  # type: ignore[arg-type]
            language="auto",
            clean_enabled=False,
            snippets_enabled=False,
        )


async def test_file_too_large_raises(db_session, monkeypatch):
    user = await _make_user_in_session(db_session)
    await db_session.commit()

    coordinator, _, _ = _build_coordinator(db_session)

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
            snippets_enabled=False,
        )


async def test_audio_too_long_raises(db_session, monkeypatch):
    user = await _make_user_in_session(db_session)
    await db_session.commit()

    coordinator, _, _ = _build_coordinator(db_session)

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
            snippets_enabled=False,
        )


async def test_invalid_language_raises(db_session):
    user = await _make_user_in_session(db_session)
    await db_session.commit()

    coordinator, _, _ = _build_coordinator(db_session)

    upload = _FakeUpload("clip.mp3", b"x" * 16)

    with pytest.raises(InvalidLanguageException):
        await coordinator.process_audio(
            user_id=user.id,
            file=upload,  # type: ignore[arg-type]
            language="not-a-real-code-123",
            clean_enabled=False,
            snippets_enabled=False,
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
    coordinator = TranscriptionCoordinator(
        db=db_session,
        transcription_service=service,
        snippet_service=SnippetService(db=db_session),
        cleanup_service=_StubCleanupService(cleaned_text="ignored"),
    )

    upload = _FakeUpload("clip.mp3", b"x" * 16)

    with pytest.raises(TranscriptionFailedException):
        await coordinator.process_audio(
            user_id=user.id,
            file=upload,  # type: ignore[arg-type]
            language="auto",
            clean_enabled=False,
            snippets_enabled=False,
        )


def test_transcription_response_schema_fields():
    resp = TranscriptionResponse(
        raw_text="hi",
        cleaned_text="hi",
        detected_language="english",
        audio_duration_secs=1.5,
        latency_ms=42.0,
    )
    assert resp.success is True
    assert resp.raw_text == "hi"
    assert resp.detected_language == "english"
    assert resp.audio_duration_secs == 1.5
    assert resp.latency_ms == 42.0


# --- Full-pipeline tests for issue #4 ---


async def _seed_snippet(
    db_session: Any,
    user: User,
    shortcut: str,
    expansion: str,
) -> Snippet:
    snippet = Snippet(
        user_id=user.id, shortcut=shortcut, expansion=expansion, archived=False
    )
    db_session.add(snippet)
    await db_session.flush()
    return snippet


async def test_pipeline_clean_true_without_snippets_persists_cleanup(db_session):
    user = await _make_user_in_session(db_session)
    await db_session.commit()

    coordinator, _, cleanup = _build_coordinator(
        db_session,
        whisper_text="hello there",
        cleaned_text="Hello there.",
    )

    upload = _FakeUpload("clip.mp3", b"x" * 16)
    result = await coordinator.process_audio(
        user_id=user.id,
        file=upload,  # type: ignore[arg-type]
        language="auto",
        clean_enabled=True,
        snippets_enabled=False,
    )

    assert result.cleaned_text == "Hello there."
    assert result.raw_text == "hello there"
    assert cleanup.calls == ["hello there"]

    cleanup_rows = (await db_session.execute(select(Cleanup))).scalars().all()
    assert len(cleanup_rows) == 1
    assert cleanup_rows[0].cleaned_text == "Hello there."
    assert cleanup_rows[0].model == "test-cleanup-model"

    link_rows = (
        await db_session.execute(select(CleanupSnippet))
    ).scalars().all()
    assert link_rows == []


async def test_pipeline_snippets_true_without_clean_expands_in_raw(db_session):
    user = await _make_user_in_session(db_session)
    await _seed_snippet(db_session, user, "myemail", "alice@example.com")
    await db_session.commit()

    coordinator, _, cleanup = _build_coordinator(
        db_session,
        whisper_text="send mail to myemail please",
        cleaned_text="send mail to myemail please",
    )

    upload = _FakeUpload("clip.mp3", b"x" * 16)
    result = await coordinator.process_audio(
        user_id=user.id,
        file=upload,  # type: ignore[arg-type]
        language="auto",
        clean_enabled=False,
        snippets_enabled=True,
    )

    # raw_text shows the snippet-expanded version
    assert result.raw_text == "send mail to alice@example.com please"
    # cleaned_text is None since cleanup was disabled
    assert result.cleaned_text is None
    # Cleanup LLM was NOT called
    assert cleanup.calls == []

    cleanup_rows = (await db_session.execute(select(Cleanup))).scalars().all()
    assert cleanup_rows == []

    link_rows = (
        await db_session.execute(select(TranscriptionSnippet))
    ).scalars().all()
    assert len(link_rows) == 1
    assert link_rows[0].transcription_id is not None
    snippet = (
        await db_session.execute(
            select(Snippet).where(Snippet.id == link_rows[0].snippet_id)
        )
    ).scalar_one()
    assert snippet.shortcut == "myemail"

    # transcription.raw_text always holds the literal Whisper output
    tx = (await db_session.execute(select(Transcription))).scalar_one()
    assert tx.raw_text == "send mail to myemail please"





async def test_pipeline_archived_snippets_are_not_expanded(db_session):
    user = await _make_user_in_session(db_session)
    snippet = await _seed_snippet(db_session, user, "newkey", "new-value")
    await _seed_snippet(db_session, user, "oldkey", "should-not-appear")

    snippet_service = SnippetService(db=db_session)
    await snippet_service.archive_snippet(user_id=user.id, snippet_id=snippet.id)
    await db_session.commit()

    coordinator, _, _ = _build_coordinator(
        db_session,
        whisper_text="press newkey now",
        cleaned_text="press newkey now",
    )

    upload = _FakeUpload("clip.mp3", b"x" * 16)
    result = await coordinator.process_audio(
        user_id=user.id,
        file=upload,  # type: ignore[arg-type]
        language="auto",
        clean_enabled=False,
        snippets_enabled=True,
    )

    # Archived snippet is NOT expanded; raw text is the literal Whisper output.
    assert result.raw_text == "press newkey now"
    assert result.cleaned_text is None


async def test_pipeline_snippets_scoped_to_current_user(db_session):
    user = await _make_user_in_session(db_session)
    other = User(
        username="other", email="other@example.com", password_hash="x" * 80
    )
    db_session.add(other)
    await db_session.flush()
    await _seed_snippet(db_session, other, "myemail", "bob@example.com")
    await db_session.commit()

    coordinator, _, _ = _build_coordinator(
        db_session,
        whisper_text="send to myemail",
        cleaned_text="send to myemail",
    )

    upload = _FakeUpload("clip.mp3", b"x" * 16)
    result = await coordinator.process_audio(
        user_id=user.id,
        file=upload,  # type: ignore[arg-type]
        language="auto",
        clean_enabled=False,
        snippets_enabled=True,
    )

    # Other user's snippet must not leak.
    assert result.raw_text == "send to myemail"
    assert result.cleaned_text is None


async def test_pipeline_response_has_no_cleaned_text_when_both_disabled(db_session):
    user = await _make_user_in_session(db_session)
    await db_session.commit()

    coordinator, _, _ = _build_coordinator(db_session)

    upload = _FakeUpload("clip.mp3", b"x" * 16)
    result = await coordinator.process_audio(
        user_id=user.id,
        file=upload,  # type: ignore[arg-type]
        language="auto",
        clean_enabled=False,
        snippets_enabled=False,
    )

    assert result.cleaned_text is None
    assert result.raw_text == "Hello world"


async def test_pipeline_overlapping_shortcuts_use_longest_match(db_session):
    user = await _make_user_in_session(db_session)
    await _seed_snippet(db_session, user, "my", "myself")
    await _seed_snippet(db_session, user, "myemail", "alice@example.com")
    await db_session.commit()

    coordinator, _, _ = _build_coordinator(
        db_session,
        whisper_text="hi myemail",
        cleaned_text="hi myemail",
    )

    upload = _FakeUpload("clip.mp3", b"x" * 16)
    result = await coordinator.process_audio(
        user_id=user.id,
        file=upload,  # type: ignore[arg-type]
        language="auto",
        clean_enabled=False,
        snippets_enabled=True,
    )

    # The longer shortcut wins; the "my" snippet is not consumed.
    assert result.raw_text == "hi alice@example.com"
    assert result.cleaned_text is None

    tx_links = (
        await db_session.execute(select(TranscriptionSnippet))
    ).scalars().all()
    assert len(tx_links) == 1
    snippet = (
        await db_session.execute(
            select(Snippet).where(Snippet.id == tx_links[0].snippet_id)
        )
    ).scalar_one()
    assert snippet.shortcut == "myemail"


async def test_pipeline_langfuse_unavailable_does_not_break_clean(db_session):
    """If the Langfuse client raises during construction, the pipeline
    must still complete (using the fallback prompt internally)."""
    import langfuse

    original_get_client = langfuse.get_client

    def _raising_get_client() -> Any:
        raise RuntimeError("langfuse unreachable")

    langfuse.get_client = _raising_get_client  # type: ignore[assignment]
    try:
        user = await _make_user_in_session(db_session)
        await db_session.commit()

        # Patch the get_client call that the real CleanupService uses
        # so we exercise the "Langfuse configured but unreachable" path.
        # We then use a stub agent to bypass the real LLM call.
        from app.services.cleanup import CleanupService as RealCleanupService

        class _LangfuseFailCleanup(RealCleanupService):
            def _build_agent(self) -> Any:
                return _ScriptedPydanticAgent("Hello there.")

        whisper = _StubWhisperClient(text="hello there", language="english")
        cleanup = _LangfuseFailCleanup(model="gpt-4o-mini")
        # Force the agent build so the patched get_client is exercised.
        cleanup._build_agent()  # noqa: SLF001 - test-only

        coordinator = TranscriptionCoordinator(
            db=db_session,
            transcription_service=TranscriptionService(whisper_client=whisper),
            snippet_service=SnippetService(db=db_session),
            cleanup_service=cleanup,
        )

        upload = _FakeUpload("clip.mp3", b"x" * 16)
        result = await coordinator.process_audio(
            user_id=user.id,
            file=upload,  # type: ignore[arg-type]
            language="auto",
            clean_enabled=True,
            snippets_enabled=False,
        )
        assert result.cleaned_text == "Hello there."
    finally:
        langfuse.get_client = original_get_client  # type: ignore[assignment]


class _ScriptedPydanticAgent:
    """Minimal Pydantic AI Agent-like object with a ``run`` coroutine."""

    def __init__(self, scripted_output: str) -> None:
        self._scripted = scripted_output

    async def run(self, text: str) -> Any:
        return MagicMock(output=self._scripted)
