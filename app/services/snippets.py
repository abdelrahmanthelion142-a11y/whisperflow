from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import paginate
from app.models.snippets import Snippet
from app.services.exceptions import (
    DuplicateShortcutException,
    SnippetNotFoundException,
)

UNLIMITED_PAGE_SIZE = 10_000


class SnippetService:
    def __init__(self, db: AsyncSession) -> None:
        self.db: AsyncSession = db

    async def create_snippet(
        self, user_id: int, shortcut: str, expansion: str
    ) -> Snippet:
        snippet = Snippet(
            user_id=user_id,
            shortcut=shortcut,
            expansion=expansion,
        )
        self.db.add(snippet)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise DuplicateShortcutException() from None
        await self.db.refresh(snippet)
        return snippet

    async def list_paginated(
        self, user_id: int, cursor: int | None, size: int
    ) -> tuple[list[Snippet], int | None]:
        stmt = select(Snippet).where(
            Snippet.user_id == user_id, Snippet.archived.is_(False)
        )
        return await paginate(
            db=self.db,
            stmt=stmt,
            cursor=cursor,
            size=size,
            id_column=Snippet.id,
        )

    async def list_all_active(self, user_id: int) -> list[Snippet]:
        items, _ = await self.list_paginated(
            user_id=user_id, cursor=None, size=UNLIMITED_PAGE_SIZE
        )
        return items

    async def get_by_id(self, user_id: int, snippet_id: int) -> Snippet | None:
        result = await self.db.execute(
            select(Snippet).where(
                Snippet.id == snippet_id, Snippet.user_id == user_id
            )
        )
        return result.scalars().first()

    async def update_snippet(
        self,
        user_id: int,
        snippet_id: int,
        shortcut: str | None = None,
        expansion: str | None = None,
    ) -> Snippet:
        snippet = await self.get_by_id(user_id=user_id, snippet_id=snippet_id)
        if snippet is None:
            raise SnippetNotFoundException()

        if shortcut is not None:
            snippet.shortcut = shortcut
        if expansion is not None:
            snippet.expansion = expansion

        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise DuplicateShortcutException() from None
        await self.db.refresh(snippet)
        return snippet

    async def archive_snippet(self, user_id: int, snippet_id: int) -> Snippet:
        snippet = await self.get_by_id(user_id=user_id, snippet_id=snippet_id)
        if snippet is None:
            raise SnippetNotFoundException()

        snippet.archived = True
        await self.db.commit()
        await self.db.refresh(snippet)
        return snippet
