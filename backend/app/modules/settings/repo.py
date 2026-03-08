from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import User


async def get_user_by_name(session: AsyncSession, username: str) -> User | None:
    result = await session.execute(select(User).where(User.name == username))
    return result.scalar_one_or_none()
