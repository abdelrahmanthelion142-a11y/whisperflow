from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    hash_password,
    verify_access_token,
    verify_password,
)
from app.models.users import User
from app.schemas.Token import Token
from app.schemas.User import UserCreate
from app.services.exceptions import (
    EmailAlreadyExistsException,
    InvalidCredentialsException,
    InvalidTokenException,
    UsernameAlreadyExistsException,
)


class UserService:
    def __init__(self, db: AsyncSession) -> None:
        self.db: AsyncSession = db

    async def create_user(self, user: UserCreate):
        result = await self.db.execute(
            select(User).where(
                func.lower(User.username) == user.username.lower(),
            ),
        )
        existing_user = result.scalars().first()
        if existing_user:
            raise UsernameAlreadyExistsException()

        result = await self.db.execute(
            select(User).where(func.lower(User.email) == user.email.lower()),
        )
        existing_email = result.scalars().first()
        if existing_email:
            raise EmailAlreadyExistsException()
        new_user = User(
            username=user.username,
            email=user.email.lower(),
            password_hash=hash_password(user.password),
        )

        self.db.add(new_user)
        await self.db.commit()
        await self.db.refresh(new_user)
        return new_user

    async def get_access_token(self, username: str, password: str) -> Token:
        result = await self.db.execute(
            select(User).where(
                func.lower(User.email) == username.lower(),
            ),
        )
        user = result.scalars().first()

        if not user or not verify_password(password, user.password_hash):
            raise InvalidCredentialsException()

        access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            user_id=user.id,
            expires_delta=access_token_expires,
        )
        return Token(access_token=access_token, token_type="bearer")

    async def get_current_user(self, token: str):
        user_id_str = verify_access_token(token)
        if user_id_str is None:
            raise InvalidTokenException()

        try:
            user_id = int(user_id_str)
        except ValueError:
            raise InvalidTokenException()

        result = await self.db.execute(
            select(User).where(User.id == user_id),
        )
        user = result.scalars().first()
        if not user:
            raise InvalidTokenException()

        return user
