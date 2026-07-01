import tempfile
import wave
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


def _wav_bytes(duration_secs: float = 1.0) -> bytes:
    n_frames = int(duration_secs * 8000)
    buf = BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()


def _stub_whisper(text: str = "hi", language: str = "english"):
    client = MagicMock()
    client.audio.transcriptions.create = AsyncMock(
        return_value=MagicMock(text=text, language=language)
    )
    return client


def _build_router_test_app(monkeypatch, *, whisper_client):
    """Create a fresh sqlite-backed test app with get_db + llm_client patched."""
    from sqlalchemy import create_engine as _sync_create

    from app.db.base import Base
    from app.dependencies import get_db
    from app.main import app
    from app.routers import transcription as transcription_module
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    tmp_db = Path(tempfile.mkstemp(suffix=".sqlite")[1])
    db_url = f"sqlite+aiosqlite:///{tmp_db}"
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(
        bind=engine, expire_on_commit=False, class_=AsyncSession
    )

    # Schema must exist before the first request hits a fresh connection.
    sync_engine = _sync_create(f"sqlite:///{tmp_db}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    monkeypatch.setattr(transcription_module, "llm_client", whisper_client)
    return app, engine, tmp_db


@pytest.mark.asyncio
async def test_router_transcribe_success(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    whisper = _stub_whisper("Hello world", "english")
    app, engine, tmp_db = _build_router_test_app(
        monkeypatch, whisper_client=whisper
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/transcribe",
            data={"language": "auto", "clean": "false", "snippets": "true"},
            files={"file": ("clip.mp3", _wav_bytes(1.0), "audio/mpeg")},
        )
    app.dependency_overrides.clear()
    await engine.dispose()
    tmp_db.unlink(missing_ok=True)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["raw_text"] == "Hello world"
    assert body["detected_language"] == "english"


@pytest.mark.asyncio
async def test_router_unsupported_format_returns_400(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    whisper = _stub_whisper()
    app, engine, tmp_db = _build_router_test_app(
        monkeypatch, whisper_client=whisper
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/transcribe",
            data={"language": "auto"},
            files={"file": ("clip.txt", b"hello", "text/plain")},
        )
    app.dependency_overrides.clear()
    await engine.dispose()
    tmp_db.unlink(missing_ok=True)

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_router_invalid_language_returns_400(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    whisper = _stub_whisper()
    app, engine, tmp_db = _build_router_test_app(
        monkeypatch, whisper_client=whisper
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/transcribe",
            data={"language": "not-a-real-code"},
            files={"file": ("clip.mp3", _wav_bytes(1.0), "audio/mpeg")},
        )
    app.dependency_overrides.clear()
    await engine.dispose()
    tmp_db.unlink(missing_ok=True)

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_router_whisper_failure_returns_502(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    failing = MagicMock()
    failing.audio.transcriptions.create = AsyncMock(
        side_effect=RuntimeError("api down")
    )
    app, engine, tmp_db = _build_router_test_app(
        monkeypatch, whisper_client=failing
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/transcribe",
            data={"language": "auto"},
            files={"file": ("clip.mp3", _wav_bytes(1.0), "audio/mpeg")},
        )
    app.dependency_overrides.clear()
    await engine.dispose()
    tmp_db.unlink(missing_ok=True)

    assert resp.status_code == 502
