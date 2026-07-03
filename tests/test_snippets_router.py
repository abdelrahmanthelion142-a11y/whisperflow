"""Integration tests for the snippets router.

Uses FastAPI's TestClient against the snippet router with a stubbed
authentication dependency so we can exercise the full request/response
cycle without standing up the real database or auth machinery.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.dependencies import get_current_user, get_db
from app.models.users import User
from app.routers.snippets import router as snippets_router
from app.db.base import Base
import app.models.snippets  # noqa: F401


class _StubUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


async def _override_current_user():
    return _StubUser(user_id=1)


@pytest_asyncio.fixture
async def app_with_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    async def _get_db():
        async with session_factory() as session:
            yield session

    app = FastAPI()
    app.include_router(snippets_router, prefix="/api/v1")
    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _override_current_user

    # Seed a user row matching the stub id.
    async with session_factory() as session:
        user = User(
            username="seed",
            email="seed@example.com",
            password_hash="x",
        )
        user.id = 1
        session.add(user)
        await session.commit()

    yield app

    await engine.dispose()


@pytest_asyncio.fixture
async def client(app_with_db) -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app_with_db)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_create_returns_snippet(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/snippets", json={"shortcut": "myemail", "expansion": "me@example.com"}
    )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["shortcut"] == "myemail"
    assert body["expansion"] == "me@example.com"
    assert body["archived"] is False
    assert "id" in body


@pytest.mark.asyncio
async def test_duplicate_shortcut_returns_409(client: AsyncClient) -> None:
    first = await client.post(
        "/api/v1/snippets", json={"shortcut": "addr", "expansion": "a@b.com"}
    )
    assert first.status_code == 201

    dup = await client.post(
        "/api/v1/snippets", json={"shortcut": "addr", "expansion": "c@d.com"}
    )
    assert dup.status_code == 409


@pytest.mark.asyncio
async def test_list_returns_only_active(client: AsyncClient) -> None:
    create = await client.post(
        "/api/v1/snippets", json={"shortcut": "k", "expansion": "keep"}
    )
    drop = await client.post(
        "/api/v1/snippets", json={"shortcut": "d", "expansion": "drop"}
    )
    assert create.status_code == 201
    assert drop.status_code == 201

    delete = await client.delete(f"/api/v1/snippets/{drop.json()['id']}")
    assert delete.status_code == 204

    listing = await client.get("/api/v1/snippets")
    assert listing.status_code == 200
    body = listing.json()
    assert "items" in body
    assert "next_cursor" in body
    shortcuts = {s["shortcut"] for s in body["items"]}
    assert shortcuts == {"k"}


@pytest.mark.asyncio
async def test_update_changes_fields(client: AsyncClient) -> None:
    create = await client.post(
        "/api/v1/snippets",
        json={"shortcut": "old", "expansion": "old body"},
    )
    snippet_id = create.json()["id"]

    resp = await client.put(
        f"/api/v1/snippets/{snippet_id}",
        json={"shortcut": "new", "expansion": "new body"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["shortcut"] == "new"
    assert body["expansion"] == "new body"


@pytest.mark.asyncio
async def test_update_missing_returns_404(client: AsyncClient) -> None:
    resp = await client.put("/api/v1/snippets/9999", json={"shortcut": "x"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_archives_snippet(client: AsyncClient) -> None:
    create = await client.post(
        "/api/v1/snippets", json={"shortcut": "bye", "expansion": "b"}
    )
    snippet_id = create.json()["id"]

    resp = await client.delete(f"/api/v1/snippets/{snippet_id}")
    assert resp.status_code == 204

    listing = await client.get("/api/v1/snippets")
    assert all(s["id"] != snippet_id for s in listing.json()["items"])


@pytest.mark.asyncio
async def test_delete_missing_returns_404(client: AsyncClient) -> None:
    resp = await client.delete("/api/v1/snippets/9999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_returns_envelope_with_default_size(
    client: AsyncClient,
) -> None:
    for i in range(3):
        await client.post(
            "/api/v1/snippets",
            json={"shortcut": f"k{i}", "expansion": f"v{i}"},
        )

    resp = await client.get("/api/v1/snippets")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"items", "next_cursor"}
    assert len(body["items"]) == 3
    assert body["next_cursor"] is None
    assert [s["shortcut"] for s in body["items"]] == ["k2", "k1", "k0"]


@pytest.mark.asyncio
async def test_list_paginates_with_cursor(client: AsyncClient) -> None:
    created_ids: list[int] = []
    for i in range(4):
        post = await client.post(
            "/api/v1/snippets",
            json={"shortcut": f"k{i}", "expansion": f"v{i}"},
        )
        created_ids.append(post.json()["id"])

    first = await client.get("/api/v1/snippets", params={"size": 2})
    assert first.status_code == 200
    body = first.json()
    assert [s["id"] for s in body["items"]] == [created_ids[-1], created_ids[-2]]
    assert body["next_cursor"] == created_ids[-2]

    second = await client.get(
        "/api/v1/snippets",
        params={"size": 2, "cursor": body["next_cursor"]},
    )
    assert second.status_code == 200
    body2 = second.json()
    assert [s["id"] for s in body2["items"]] == [created_ids[-3], created_ids[-4]]
    assert body2["next_cursor"] is None


@pytest.mark.asyncio
async def test_list_caps_size_at_20(client: AsyncClient) -> None:
    for i in range(25):
        await client.post(
            "/api/v1/snippets",
            json={"shortcut": f"k{i:02d}", "expansion": f"v{i}"},
        )

    resp = await client.get("/api/v1/snippets", params={"size": 1000})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 20
    assert body["next_cursor"] is not None
