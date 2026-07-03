"""Integration tests for the voice_messages router.

Uses FastAPI's ASGI TestClient with a stubbed authentication
dependency and an in-memory SQLite database, mirroring the pattern
from ``tests/test_snippets_router.py`` so the full request/response
cycle is exercised without the real database or auth machinery.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.base import Base
from app.dependencies import get_current_user, get_db
from app.models.cleanups import Cleanup
from app.models.transcriptions import Transcription
from app.models.users import User
from app.models.voice_messages import VoiceMessage
from app.routers.voice_messages import router as voice_messages_router


class _StubUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


def _make_current_user_override(user_id: int):
    async def _override_current_user():
        return _StubUser(user_id=user_id)

    return _override_current_user


@pytest_asyncio.fixture
async def app_with_db() -> AsyncGenerator[
    tuple[FastAPI, async_sessionmaker[AsyncSession]], None
]:
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def _get_db():
        async with session_factory() as session:
            yield session

    app = FastAPI()
    app.include_router(voice_messages_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _make_current_user_override(
        user_id=1
    )

    async with session_factory() as session:
        user = User(username="seed", email="seed@example.com", password_hash="x")
        user.id = 1
        session.add(user)
        await session.commit()

    yield app, session_factory

    await engine.dispose()


@pytest_asyncio.fixture
async def client(
    app_with_db: tuple[FastAPI, async_sessionmaker[AsyncSession]],
) -> AsyncGenerator[AsyncClient, None]:
    app, _ = app_with_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def session_factory(
    app_with_db: tuple[FastAPI, async_sessionmaker[AsyncSession]],
) -> async_sessionmaker[AsyncSession]:
    _, sf = app_with_db
    return sf


async def _seed_voice_message(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: int,
    filename: str,
) -> int:
    async with session_factory() as session:
        vm = VoiceMessage(
            user_id=user_id,
            filename=filename,
            language="en",
            snippets_enabled=True,
            clean_enabled=True,
            file_size_bytes=1024,
            audio_duration_secs=1.0,
        )
        session.add(vm)
        await session.commit()
        await session.refresh(vm)
        return vm.id


async def _seed_full_voice_message(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    user_id: int,
    filename: str,
    raw_text: str,
    cleaned_text: str,
) -> int:
    async with session_factory() as session:
        vm = VoiceMessage(
            user_id=user_id,
            filename=filename,
            language="en",
            snippets_enabled=True,
            clean_enabled=True,
            file_size_bytes=1024,
            audio_duration_secs=1.0,
        )
        session.add(vm)
        await session.commit()
        await session.refresh(vm)
        session.add(
            Transcription(
                voice_message_id=vm.id,
                raw_text=raw_text,
                detected_language="en",
                latency_ms=10.0,
                model="whisper-1",
            )
        )
        session.add(
            Cleanup(
                voice_message_id=vm.id,
                cleaned_text=cleaned_text,
                model="gpt-4o-mini",
                latency_ms=20.0,
            )
        )
        await session.commit()
        return vm.id


async def _attach_transcription(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    voice_message_id: int,
    raw_text: str,
) -> None:
    async with session_factory() as session:
        session.add(
            Transcription(
                voice_message_id=voice_message_id,
                raw_text=raw_text,
                detected_language="en",
                latency_ms=10.0,
                model="whisper-1",
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_list_history_returns_envelope(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_full_voice_message(
        session_factory,
        user_id=1,
        filename="clip.mp3",
        raw_text="raw text",
        cleaned_text="Cleaned text.",
    )

    resp = await client.get("/api/v1/voice-messages")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"items", "next_cursor"}
    assert body["next_cursor"] is None
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["filename"] == "clip.mp3"
    assert item["has_transcription"] is True
    assert item["has_cleanup"] is True
    assert item["text"] == "Cleaned text."


@pytest.mark.asyncio
async def test_list_history_falls_back_to_raw_text(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    vm_id = await _seed_voice_message(
        session_factory, user_id=1, filename="raw.mp3"
    )
    await _attach_transcription(
        session_factory, voice_message_id=vm_id, raw_text="raw only"
    )

    resp = await client.get("/api/v1/voice-messages")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["has_transcription"] is True
    assert item["has_cleanup"] is False
    assert item["text"] == "raw only"


@pytest.mark.asyncio
async def test_list_history_text_null_when_no_transcription_or_cleanup(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_voice_message(
        session_factory, user_id=1, filename="empty.mp3"
    )

    resp = await client.get("/api/v1/voice-messages")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["has_transcription"] is False
    assert item["has_cleanup"] is False
    assert item["text"] is None


@pytest.mark.asyncio
async def test_list_history_orders_newest_first(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_voice_message(session_factory, user_id=1, filename="first.mp3")
    await _seed_voice_message(session_factory, user_id=1, filename="second.mp3")
    await _seed_voice_message(session_factory, user_id=1, filename="third.mp3")

    resp = await client.get("/api/v1/voice-messages")

    assert resp.status_code == 200
    body = resp.json()
    assert [item["filename"] for item in body["items"]] == [
        "third.mp3",
        "second.mp3",
        "first.mp3",
    ]


@pytest.mark.asyncio
async def test_list_history_paginates_with_cursor(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    created_ids: list[int] = []
    for i in range(4):
        vid = await _seed_voice_message(
            session_factory, user_id=1, filename=f"clip-{i}.mp3"
        )
        created_ids.append(vid)

    first = await client.get("/api/v1/voice-messages", params={"size": 2})
    assert first.status_code == 200
    body = first.json()
    assert [item["id"] for item in body["items"]] == [
        created_ids[-1],
        created_ids[-2],
    ]
    assert body["next_cursor"] == created_ids[-2]

    second = await client.get(
        "/api/v1/voice-messages",
        params={"size": 2, "cursor": body["next_cursor"]},
    )
    assert second.status_code == 200
    body2 = second.json()
    assert [item["id"] for item in body2["items"]] == [
        created_ids[-3],
        created_ids[-4],
    ]
    assert body2["next_cursor"] is None


@pytest.mark.asyncio
async def test_list_history_caps_size_at_20(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    for i in range(25):
        await _seed_voice_message(
            session_factory, user_id=1, filename=f"clip-{i:02d}.mp3"
        )

    resp = await client.get(
        "/api/v1/voice-messages", params={"size": 1000}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 20
    assert body["next_cursor"] is not None


@pytest.mark.asyncio
async def test_list_history_scopes_to_user(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        other = User(
            username="other", email="other@example.com", password_hash="x"
        )
        other.id = 2
        session.add(other)
        await session.commit()
    await _seed_voice_message(
        session_factory, user_id=2, filename="theirs.mp3"
    )

    resp = await client.get("/api/v1/voice-messages")

    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []


@pytest.mark.asyncio
async def test_list_history_requires_auth() -> None:
    """Without a get_current_user override the route should 401."""
    engine: AsyncEngine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def _get_db():
        async with session_factory() as session:
            yield session

    app = FastAPI()
    app.include_router(voice_messages_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = _get_db
    # Note: no override for get_current_user; OAuth2PasswordBearer kicks in.

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/api/v1/voice-messages")
    await engine.dispose()

    assert resp.status_code == 401
