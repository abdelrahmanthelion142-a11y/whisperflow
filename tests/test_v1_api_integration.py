"""End-to-end integration test across the v1 API.

Drives the full slice most users care about — uploading audio, getting
a transcription back, and seeing the result in history — so that
breakage across routing, services, and the database surfaces in one
run.

Mirrors the patterns already used in
``tests/test_transcription_router.py`` and
``tests/test_snippets_router.py``:

- ``get_db`` is overridden to an in-memory SQLite session.
- The ``llm_client`` used by the transcription router is monkeypatched
  to return scripted text.
- ``CleanupService`` is replaced in the transcription router with a
  subclass whose ``_run_agent`` returns scripted text.
- ``get_current_user`` is overridden so the auth-protected endpoints
  resolve to a real user row in the test database.

Assertions cover the external behavior — HTTP status codes, response
JSON shape, and the values the user sees — not internal implementation
details.
"""
from __future__ import annotations

import wave
from functools import partial
from io import BytesIO
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from app.db.base import Base
from app.dependencies import get_current_user, get_db
from app.main import app
from app.models.users import User
from app.models.voice_messages import VoiceMessage
from app.routers import transcription as transcription_module
from app.services.cleanup import CleanupService


def _wav_bytes(duration_secs: float = 1.0) -> bytes:
    n_frames = int(duration_secs * 8000)
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()


def _stub_whisper(text: str, language: str = "english") -> MagicMock:
    client = MagicMock()
    client.audio.transcriptions.create = AsyncMock(
        return_value=MagicMock(text=text, language=language)
    )
    return client


class _StubUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


class _ScriptedCleanupService(CleanupService):
    """CleanupService subclass whose ``_run_agent`` returns a scripted output."""

    def __init__(self, cleaned_text: str) -> None:
        super().__init__(max_retries=0)
        self._scripted = cleaned_text

    async def _run_agent(self, text: str) -> str:
        return self._scripted


@pytest_asyncio.fixture
async def end_to_end_app():
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    # Seed a user row with id=0 so the transcribe router's user_id=0
    # placeholder satisfies the FK constraint and the auth-protected
    # endpoints resolve to a real row.
    async with session_factory() as session:
        user = User(username="alice", email="alice@example.com", password_hash="x")
        user.id = 0
        session.add(user)
        await session.commit()

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    async def _override_current_user():
        return _StubUser(user_id=0)

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_current_user

    yield app, session_factory

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_v1_api_full_slice_end_to_end(monkeypatch, end_to_end_app):
    """Drive transcribe -> history -> paginate -> snippets in one run.

    Three voice messages are created in all three states of the text
    fallback chain (cleanup, raw, null) so the test can assert every
    branch of ``cleanup -> raw -> null`` via paginated history calls.
    """
    test_app, session_factory = end_to_end_app
    transport = ASGITransport(app=test_app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # --- 1. Seed a voice message with no transcription or cleanup -----
        # Covers the null branch of the fallback chain.
        async with session_factory() as session:
            empty_vm = VoiceMessage(
                user_id=0,
                filename="empty.mp3",
                language="auto",
                snippets_enabled=False,
                clean_enabled=False,
                file_size_bytes=1024,
                audio_duration_secs=1.0,
            )
            session.add(empty_vm)
            await session.commit()
            await session.refresh(empty_vm)
            empty_id = empty_vm.id

        # --- 2. POST /api/v1/transcribe (cleanup disabled) -----------------
        # Covers the raw branch of the fallback chain.
        monkeypatch.setattr(
            transcription_module,
            "llm_client",
            _stub_whisper("First clip", "english"),
        )
        resp = await client.post(
            "/api/v1/transcribe",
            data={"language": "auto", "clean": "false", "snippets": "false"},
            files={"file": ("clip.mp3", _wav_bytes(1.0), "audio/mpeg")},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert body["raw_text"] == "First clip"
        assert body["cleaned_text"] is None

        # --- 3. POST /api/v1/transcribe (cleanup enabled) ------------------
        # Covers the cleanup branch of the fallback chain.
        monkeypatch.setattr(
            transcription_module,
            "llm_client",
            _stub_whisper("Second clip", "english"),
        )
        monkeypatch.setattr(
            transcription_module,
            "CleanupService",
            partial(_ScriptedCleanupService, cleaned_text="Second clip."),
        )
        resp = await client.post(
            "/api/v1/transcribe",
            data={"language": "auto", "clean": "true", "snippets": "false"},
            files={"file": ("clip2.mp3", _wav_bytes(1.0), "audio/mpeg")},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["raw_text"] == "Second clip"
        assert body["cleaned_text"] == "Second clip."

        # --- 4. GET /api/v1/voice-messages (page 1: newest = cleanup) ------
        resp = await client.get(
            "/api/v1/voice-messages", params={"size": 1}
        )
        assert resp.status_code == 200, resp.text
        first = resp.json()
        assert set(first.keys()) == {"items", "next_cursor"}
        assert len(first["items"]) == 1
        assert first["items"][0]["text"] == "Second clip."
        assert first["items"][0]["has_transcription"] is True
        assert first["items"][0]["has_cleanup"] is True
        assert first["next_cursor"] is not None

        # --- 5. Follow cursor (page 2: raw branch) -------------------------
        resp = await client.get(
            "/api/v1/voice-messages",
            params={"size": 1, "cursor": first["next_cursor"]},
        )
        assert resp.status_code == 200, resp.text
        second = resp.json()
        assert len(second["items"]) == 1
        assert second["items"][0]["text"] == "First clip"
        assert second["items"][0]["has_transcription"] is True
        assert second["items"][0]["has_cleanup"] is False
        assert second["next_cursor"] is not None

        # --- 6. Follow cursor (page 3: null branch) ------------------------
        resp = await client.get(
            "/api/v1/voice-messages",
            params={"size": 1, "cursor": second["next_cursor"]},
        )
        assert resp.status_code == 200, resp.text
        third = resp.json()
        assert len(third["items"]) == 1
        assert third["items"][0]["id"] == empty_id
        assert third["items"][0]["text"] is None
        assert third["items"][0]["has_transcription"] is False
        assert third["items"][0]["has_cleanup"] is False
        assert third["next_cursor"] is None

        # --- 7. GET /api/v1/snippets?size=... (shared Page envelope) -------
        resp = await client.get("/api/v1/snippets", params={"size": 20})
        assert resp.status_code == 200, resp.text
        snippets = resp.json()
        assert set(snippets.keys()) == {"items", "next_cursor"}
        assert snippets["items"] == []
        assert snippets["next_cursor"] is None
