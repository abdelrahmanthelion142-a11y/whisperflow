from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import oauth2_scheme
from app.db.database import AsyncSessionLocal
from app.models.users import User
from app.services.exceptions import InvalidTokenException
from app.services.users import UserService


async def get_db():
    async with AsyncSessionLocal() as session:  # type:ignore
        yield session


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    user_service = UserService(db=db)
    try:
        return await user_service.get_current_user(token)
    except InvalidTokenException as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
