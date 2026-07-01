"""Test fixtures for snippet CRUD tests.

Uses an in-memory aiosqlite database per test so the test session
never touches the real Postgres database.
"""
from __future__ import annotations

import asyncio
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import hash_password
from app.db.base import Base
from app.models.users import User
import app.models.snippets  # noqa: F401  (register Snippet model with Base)


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


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
