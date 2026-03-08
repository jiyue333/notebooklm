from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.config import Settings, get_settings
from app.infra.db.session import get_db_session

bearer_scheme = HTTPBearer(auto_error=False)


async def db_session_dep() -> AsyncIterator[AsyncSession]:
    async for session in get_db_session():
        yield session


def settings_dep() -> Settings:
    return get_settings()


def request_id_dep(request: Request) -> str:
    return getattr(request.state, "request_id", "")


async def raw_token_dep(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError(401, "authentication required", code="auth_required")
    return credentials.credentials


async def current_user_dep(
    token: str = Depends(raw_token_dep),
    session: AsyncSession = Depends(db_session_dep),
):
    from app.modules.auth.service import get_user_by_token

    return await get_user_by_token(session, token)
