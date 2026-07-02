"""Shared test fixtures for the Whisperflow test suite.

Uses an in-memory aiosqlite database per test so the test session never
touches the real Postgres database.
"""
from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Use a static secret for tests; loaded BEFORE app modules read settings.
os.environ.setdefault("POSTGRES_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-key-for-testing-only")
os.environ.setdefault("DATABASE_PASSWORD", "test-db-password")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.dependencies import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models.users import User  # noqa: E402

# Import model modules for their side effect of registering them with Base.metadata.
from app.models import cleanup_snippets  # noqa: E402, F401
from app.models import cleanups  # noqa: E402, F401
from app.models import snippets  # noqa: E402, F401
from app.models import transcription_snippets  # noqa: E402, F401
from app.models import transcriptions  # noqa: E402, F401
from app.models import voice_messages  # noqa: E402, F401

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: Any) -> AsyncGenerator[AsyncSession, None]:
    session_factory = async_sessionmaker(
        bind=db_engine, expire_on_commit=False, class_=AsyncSession
    )
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        username="tester",
        email="tester@example.com",
        password_hash=hash_password("supersecret123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def client(db_engine: Any) -> AsyncGenerator[AsyncClient, None]:
    session_factory = async_sessionmaker(
        bind=db_engine, expire_on_commit=False, class_=AsyncSession
    )

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def settings_override(monkeypatch: pytest.MonkeyPatch) -> Any:
    return monkeypatch
