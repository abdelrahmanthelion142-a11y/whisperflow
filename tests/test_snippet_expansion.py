"""End-to-end tests for the four clean × snippets cases.

Every case asserts the response fields, persisted rows, junction
tables, and the literal Whisper-audit invariant on
``transcriptions.raw_text``.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select

from app.models.cleanup_snippets import CleanupSnippet
from app.models.cleanups import Cleanup
from app.models.snippets import Snippet
from app.models.transcription_snippets import TranscriptionSnippet
from app.models.transcriptions import Transcription
from app.models.users import User
from app.schemas.Transcription import CleanupResult
from app.services.cleanup import CleanupService
from app.services.snippets import SnippetService
from app.services.transcription import TranscriptionService


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
            return_value=MagicMock(text=text, language=language)
        )


class _StubCleanupService(CleanupService):
    """CleanupService subclass that returns a scripted output for testing."""

    def __init__(self, cleaned_text: str, model: str = "test-cleanup-model") -> None:
        super().__init__(model=model)
        self._scripted = cleaned_text
        self.calls: list[str] = []

    async def _run_agent(self, text: str) -> str:
        self.calls.append(text)
        return self._scripted


async def _make_user(db_session: Any) -> User:
    user = User(
        username="alice",
        email="alice@example.com",
        password_hash="x" * 80,
    )
    db_session.add(user)
    await db_session.flush()
    return user


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


# ── Four cases ──────────────────────────────────────────────────────────


async def test_clean_true_snippets_true(db_session):
    """Case 1: clean=True, snippets=True.

    * LLM receives raw Whisper text.
    * response.raw_text = literal Whisper.
    * response.cleaned_text = LLM output with snippets expanded.
    * Cleanup row + both junction tables populated.
    """
    user = await _make_user(db_session)
    await _seed_snippet(db_session, user, "myemail", "alice@example.com")
    await db_session.commit()

    whisper_text = "send mail to myemail please"
    llm_output = "Send mail to myemail please."

    whisper = _StubWhisperClient(text=whisper_text)
    cleanup = _StubCleanupService(cleaned_text=llm_output)
    coordinator = _build_coordinator(db_session, whisper, cleanup)

    upload = _FakeUpload("clip.mp3", b"x" * 16)
    result = await coordinator.process_audio(
        user_id=user.id,
        file=upload,
        language="auto",
        clean_enabled=True,
        snippets_enabled=True,
    )

    assert result.raw_text == whisper_text
    assert result.cleaned_text == "Send mail to alice@example.com please."
    assert cleanup.calls == [whisper_text]

    cleanup_rows = (await db_session.execute(select(Cleanup))).scalars().all()
    assert len(cleanup_rows) == 1
    assert cleanup_rows[0].cleaned_text == "Send mail to alice@example.com please."

    tx_links = (
        await db_session.execute(select(TranscriptionSnippet))
    ).scalars().all()
    assert len(tx_links) == 1

    cleanup_links = (
        await db_session.execute(select(CleanupSnippet))
    ).scalars().all()
    assert len(cleanup_links) == 1

    tx = (await db_session.execute(select(Transcription))).scalar_one()
    assert tx.raw_text == whisper_text


async def test_clean_true_snippets_false(db_session):
    """Case 2: clean=True, snippets=False.

    * LLM receives raw Whisper text.
    * response.raw_text = literal Whisper.
    * response.cleaned_text = LLM output verbatim (no expansion).
    * Cleanup row exists; no junction rows.
    """
    user = await _make_user(db_session)
    await db_session.commit()

    whisper_text = "hello there"
    llm_output = "Hello there."

    whisper = _StubWhisperClient(text=whisper_text)
    cleanup = _StubCleanupService(cleaned_text=llm_output)
    coordinator = _build_coordinator(db_session, whisper, cleanup)

    upload = _FakeUpload("clip.mp3", b"x" * 16)
    result = await coordinator.process_audio(
        user_id=user.id,
        file=upload,
        language="auto",
        clean_enabled=True,
        snippets_enabled=False,
    )

    assert result.raw_text == whisper_text
    assert result.cleaned_text == llm_output
    assert cleanup.calls == [whisper_text]

    cleanup_rows = (await db_session.execute(select(Cleanup))).scalars().all()
    assert len(cleanup_rows) == 1
    assert cleanup_rows[0].cleaned_text == llm_output

    tx_links = (
        await db_session.execute(select(TranscriptionSnippet))
    ).scalars().all()
    assert tx_links == []

    cleanup_links = (
        await db_session.execute(select(CleanupSnippet))
    ).scalars().all()
    assert cleanup_links == []

    tx = (await db_session.execute(select(Transcription))).scalar_one()
    assert tx.raw_text == whisper_text


async def test_clean_false_snippets_true(db_session):
    """Case 3: clean=False, snippets=True.

    * No LLM call.
    * response.raw_text = raw text with snippets expanded.
    * response.cleaned_text = None.
    * No cleanup row; transcription junction populated.
    """
    user = await _make_user(db_session)
    await _seed_snippet(db_session, user, "myemail", "alice@example.com")
    await db_session.commit()

    whisper_text = "send mail to myemail please"
    expanded = "send mail to alice@example.com please"

    whisper = _StubWhisperClient(text=whisper_text)
    cleanup = _StubCleanupService(cleaned_text="SHOULD NOT BE CALLED")
    coordinator = _build_coordinator(db_session, whisper, cleanup)

    upload = _FakeUpload("clip.mp3", b"x" * 16)
    result = await coordinator.process_audio(
        user_id=user.id,
        file=upload,
        language="auto",
        clean_enabled=False,
        snippets_enabled=True,
    )

    assert result.raw_text == expanded
    assert result.cleaned_text is None
    assert cleanup.calls == []

    cleanup_rows = (await db_session.execute(select(Cleanup))).scalars().all()
    assert cleanup_rows == []

    tx_links = (
        await db_session.execute(select(TranscriptionSnippet))
    ).scalars().all()
    assert len(tx_links) == 1

    tx = (await db_session.execute(select(Transcription))).scalar_one()
    assert tx.raw_text == whisper_text


async def test_clean_false_snippets_false(db_session):
    """Case 4: clean=False, snippets=False.

    * No LLM call, no expansion.
    * response.raw_text = literal Whisper.
    * response.cleaned_text = None.
    * No cleanup row, no junction rows.
    """
    user = await _make_user(db_session)
    await db_session.commit()

    whisper_text = "Hello world"

    whisper = _StubWhisperClient(text=whisper_text)
    cleanup = _StubCleanupService(cleaned_text="SHOULD NOT BE CALLED")
    coordinator = _build_coordinator(db_session, whisper, cleanup)

    upload = _FakeUpload("clip.mp3", b"x" * 16)
    result = await coordinator.process_audio(
        user_id=user.id,
        file=upload,
        language="auto",
        clean_enabled=False,
        snippets_enabled=False,
    )

    assert result.raw_text == whisper_text
    assert result.cleaned_text is None
    assert cleanup.calls == []

    cleanup_rows = (await db_session.execute(select(Cleanup))).scalars().all()
    assert cleanup_rows == []

    tx_links = (
        await db_session.execute(select(TranscriptionSnippet))
    ).scalars().all()
    assert tx_links == []

    tx = (await db_session.execute(select(Transcription))).scalar_one()
    assert tx.raw_text == whisper_text


# ── Additional invariants ───────────────────────────────────────────────


async def test_overlapping_shortcuts_leftmost_longest(db_session):
    """Overlapping shortcuts resolve leftmost-longest; shorter match is
    not consumed."""
    user = await _make_user(db_session)
    await _seed_snippet(db_session, user, "my", "myself")
    await _seed_snippet(db_session, user, "myemail", "alice@example.com")
    await db_session.commit()

    whisper = _StubWhisperClient(text="hi myemail")
    coordinator = _build_coordinator(db_session, whisper, _StubCleanupService(""))

    upload = _FakeUpload("clip.mp3", b"x" * 16)
    result = await coordinator.process_audio(
        user_id=user.id,
        file=upload,
        language="auto",
        clean_enabled=False,
        snippets_enabled=True,
    )

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


async def test_archived_snippets_not_expanded(db_session):
    user = await _make_user(db_session)
    await _seed_snippet(db_session, user, "newkey", "new-value")
    snippet = await _seed_snippet(db_session, user, "oldkey", "should-not-appear")
    await db_session.commit()

    snippet_service = SnippetService(db=db_session)
    await snippet_service.archive_snippet(user_id=user.id, snippet_id=snippet.id)
    await db_session.commit()

    whisper = _StubWhisperClient(text="press newkey now")
    coordinator = _build_coordinator(
        db_session, whisper, _StubCleanupService(""), snippet_service=snippet_service
    )

    upload = _FakeUpload("clip.mp3", b"x" * 16)
    result = await coordinator.process_audio(
        user_id=user.id,
        file=upload,
        language="auto",
        clean_enabled=False,
        snippets_enabled=True,
    )

    assert result.raw_text == "press new-value now"
    assert result.cleaned_text is None


async def test_snippet_scope_per_user(db_session):
    user = await _make_user(db_session)
    other = User(
        username="other", email="other@example.com", password_hash="x" * 80
    )
    db_session.add(other)
    await db_session.flush()
    await _seed_snippet(db_session, other, "myemail", "bob@example.com")
    await db_session.commit()

    whisper = _StubWhisperClient(text="send to myemail")
    coordinator = _build_coordinator(db_session, whisper, _StubCleanupService(""))

    upload = _FakeUpload("clip.mp3", b"x" * 16)
    result = await coordinator.process_audio(
        user_id=user.id,
        file=upload,
        language="auto",
        clean_enabled=False,
        snippets_enabled=True,
    )

    assert result.raw_text == "send to myemail"
    assert result.cleaned_text is None


# ── Cleanup service thin unit test ──────────────────────────────────────


async def test_cleanup_service_invokes_agent_once():
    """CleanupService.clean(text) invokes the agent exactly once and
    returns the agent's output verbatim."""
    calls: list[str] = []

    class _ScriptedAgentCleanup(CleanupService):
        async def _run_agent(self, text: str) -> str:
            calls.append(text)
            return "Cleaned: " + text

    service = _ScriptedAgentCleanup(model="test-model")
    result = await service.clean("raw input")

    assert isinstance(result, CleanupResult)
    assert result.cleaned_text == "Cleaned: raw input"
    assert len(calls) == 1
    assert result.model == "test-model"
    assert result.latency_ms >= 0


# ── Helpers ─────────────────────────────────────────────────────────────


def _build_coordinator(
    db_session: Any,
    whisper_client: _StubWhisperClient | None = None,
    cleanup_service: _StubCleanupService | None = None,
    snippet_service: SnippetService | None = None,
) -> Any:
    from app.services.coordinator import TranscriptionCoordinator

    whisper = whisper_client or _StubWhisperClient()
    ts = TranscriptionService(whisper_client=whisper)
    ss = snippet_service or SnippetService(db=db_session)
    cs = cleanup_service or _StubCleanupService(cleaned_text="")
    return TranscriptionCoordinator(
        db=db_session,
        transcription_service=ts,
        snippet_service=ss,
        cleanup_service=cs,
    )
