from datetime import datetime, timedelta, timezone
from fastapi.security import OAuth2PasswordBearer
import jwt
from pwdlib import PasswordHash
from app.core.config import settings
from typing import Any

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/users/token")
hash_function = PasswordHash.recommended()


def hash_password(password):
    return hash_function.hash(password)


def verify_password(plain_password, hashed_password) -> bool:
    return hash_function.verify(plain_password, hashed_password)


from typing import Any

def create_access_token(user_id: int, expires_delta: timedelta | None = None) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=30)

    to_encode: dict[str, Any] = {
        "sub": str(user_id),
        "exp": expire
    }
    
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET.get_secret_value(), algorithm=settings.JWT_ALG
    )
    return encoded_jwt


def verify_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET.get_secret_value(),
            algorithms=[settings.JWT_ALG],
            options={"require": ["exp", "sub"]},
        )
    except jwt.InvalidTokenError:
        return None
    else:
        return payload.get("sub")