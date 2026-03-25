from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.infra.security.passwords import hash_password, verify_password
from app.modules.auth import repo as auth_repo
from app.modules.auth.models import User
from app.modules.auth.service import build_user_view
from app.modules.settings.service import invalidate_settings_view_cache


async def update_profile(session: AsyncSession, *, user: User, username: str) -> dict:
    normalized_username = username.strip()
    existing = await auth_repo.get_user_by_name(session, normalized_username)
    if existing is not None and existing.id != user.id:
        raise AppError(409, "用户名已存在", code="username_conflict")

    user.name = normalized_username
    await session.commit()
    await session.refresh(user)
    await invalidate_settings_view_cache(user_id=user.id)
    return build_user_view(user).model_dump()


async def update_password(
    session: AsyncSession,
    *,
    user: User,
    old_password: str,
    new_password: str,
    confirm_password: str,
) -> None:
    if new_password != confirm_password:
        raise AppError(422, "两次输入的新密码不一致", code="password_confirmation_mismatch")
    if not verify_password(old_password, user.password_hash):
        raise AppError(422, "旧密码不正确", code="old_password_invalid")

    user.password_hash = hash_password(new_password)
    await session.commit()



async def update_avatar(session: AsyncSession, *, user: User, avatar_url: str) -> dict:
    user.avatar_url = avatar_url
    await session.commit()
    await session.refresh(user)
    await invalidate_settings_view_cache(user_id=user.id)
    return build_user_view(user).model_dump()
