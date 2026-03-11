from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import AuthToken, User


async def get_user_by_name(session: AsyncSession, username: str) -> User | None:
    result = await session.execute(select(User).where(User.name == username))
    return result.scalar_one_or_none()


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: str) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_user_by_token_hash(
    session: AsyncSession,
    token_hash: str,
    *,
    now: datetime,
) -> User | None:
    result = await session.execute(
        select(User)
        .join(AuthToken, AuthToken.user_id == User.id)
        .where(AuthToken.token_hash == token_hash, AuthToken.expires_at > now)
    )
    return result.scalar_one_or_none()


async def create_auth_token(
    session: AsyncSession,
    *,
    user_id: str,
    token_hash: str,
    expires_at: datetime,
    created_at: datetime,
) -> AuthToken:
    token = AuthToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
        created_at=created_at,
    )
    session.add(token)
    await session.flush()
    return token


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    email: str,
    password_hash: str,
) -> User:
    user = User(
        name=username,
        email=email,
        password_hash=password_hash,
        settings_json={},
    )
    session.add(user)
    await session.flush()
    return user


async def revoke_token(session: AsyncSession, token_hash: str) -> None:
    await session.execute(delete(AuthToken).where(AuthToken.token_hash == token_hash))
