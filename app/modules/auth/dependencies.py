import uuid
from collections.abc import Awaitable, Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.modules.auth.service import get_user_by_id
from app.modules.users.models import User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise _UNAUTHORIZED

    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError:
        raise _UNAUTHORIZED

    if payload.get("type") != "access":
        raise _UNAUTHORIZED

    subject = payload.get("sub")
    if subject is None:
        raise _UNAUTHORIZED

    user = await get_user_by_id(db, uuid.UUID(subject))
    if user is None or not user.is_active:
        raise _UNAUTHORIZED

    return user


def require_roles(*roles: UserRole) -> Callable[[User], Awaitable[User]]:
    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user

    return dependency
