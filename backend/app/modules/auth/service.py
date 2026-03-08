from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.modules.auth import repo
from app.modules.auth.models import User
from app.modules.auth.schemas import UserView
from app.modules.auth.security import (
    build_token_expiry,
    generate_session_token,
    hash_session_token,
    verify_password,
)


def build_user_view(user: User) -> UserView:
    return UserView(
        id=user.id,
        name=user.name,
        email=user.email,
        avatar=user.avatar_url,
    )


async def login(session: AsyncSession, *, username: str, password: str) -> tuple[str, UserView]:
    normalized_username = username.strip()
    if not normalized_username or not password:
        raise AppError(422, "username and password are required")

    user = await repo.get_user_by_name(session, normalized_username)
    if user is None or not verify_password(password, user.password_hash):
        raise AppError(401, "用户名或密码错误", code="invalid_credentials")

    raw_token = generate_session_token()
    await repo.create_auth_token(
        session,
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
        expires_at=build_token_expiry(),
        created_at=datetime.now(UTC),
    )
    await session.commit()
    return raw_token, build_user_view(user)


async def logout(session: AsyncSession, token: str) -> None:
    await repo.revoke_token(session, hash_session_token(token))
    await session.commit()


async def get_user_by_token(session: AsyncSession, token: str) -> User:
    user = await repo.get_user_by_token_hash(
        session,
        hash_session_token(token),
        now=datetime.now(UTC),
    )
    if user is None:
        raise AppError(401, "登录状态已失效，请重新登录", code="invalid_token")
    return user
