from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.infra.security.passwords import hash_password, verify_password
from app.infra.security.session_tokens import (
    build_token_expiry,
    generate_session_token,
    hash_session_token,
)
from app.modules.auth import repo
from app.modules.auth.models import User
from app.modules.auth.schemas import UserView


def build_user_view(user: User) -> UserView:
    return UserView(
        id=user.id,
        name=user.name,
        email=user.email,
        avatar=user.avatar_url,
    )

async def lookup_email(session: AsyncSession, *, email: str) -> bool:
    normalized_email = _normalize_email(email)
    if not normalized_email:
        raise AppError(422, "email is required")
    if "@" not in normalized_email:
        raise AppError(422, "请输入有效的邮箱地址", code="invalid_email")
    return await repo.get_user_by_email(session, normalized_email) is not None

def _normalize_email(email: str) -> str:
    return email.strip().lower()

async def login(session: AsyncSession, *, username: str, password: str) -> tuple[str, UserView]:
    normalized_username = username.strip()
    if not normalized_username or not password:
        raise AppError(422, "username and password are required")

    user = await _get_user_for_login(session, normalized_username)
    if user is None or not verify_password(password, user.password_hash):
        raise AppError(401, "用户名或密码错误", code="invalid_credentials")

    raw_token = await _issue_session_token(session, user)
    await session.commit()
    return raw_token, build_user_view(user)


async def register(
    session: AsyncSession,
    *,
    username: str,
    email: str,
    password: str,
) -> tuple[str, UserView]:
    normalized_username = username.strip()
    normalized_email = _normalize_email(email)
    if not normalized_username or not normalized_email or not password:
        raise AppError(422, "username, email and password are required")
    if "@" not in normalized_email:
        raise AppError(422, "请输入有效的邮箱地址", code="invalid_email")

    if await repo.get_user_by_name(session, normalized_username) is not None:
        raise AppError(409, "用户名已存在", code="username_conflict")
    if await repo.get_user_by_email(session, normalized_email) is not None:
        raise AppError(409, "邮箱已存在", code="email_conflict")

    try:
        user = await repo.create_user(
            session,
            username=normalized_username,
            email=normalized_email,
            password_hash=hash_password(password),
        )
        raw_token = await _issue_session_token(session, user)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise AppError(409, "用户名或邮箱已存在", code="user_conflict") from exc

    return raw_token, build_user_view(user)

async def _issue_session_token(session: AsyncSession, user: User) -> str:
    raw_token = generate_session_token()
    await repo.create_auth_token(
        session,
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
        expires_at=build_token_expiry(),
        created_at=datetime.now(UTC),
    )
    return raw_token

async def _get_user_for_login(session: AsyncSession, identifier: str) -> User | None:
    normalized_identifier = identifier.strip()
    if "@" in normalized_identifier:
        return await repo.get_user_by_email(session, _normalize_email(normalized_identifier))
    return await repo.get_user_by_name(session, normalized_identifier)



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



async def request_password_reset(session: AsyncSession, *, email: str) -> str | None:
    normalized_email = _normalize_email(email)
    user = await repo.get_user_by_email(session, normalized_email)
    if user is None:
        return None
    raw_token = generate_session_token()
    await repo.create_password_reset_token(
        session,
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
        expires_at=build_token_expiry(),
        created_at=datetime.now(UTC),
    )
    await session.commit()
    return raw_token


async def reset_password_with_token(session: AsyncSession, *, token: str, new_password: str, confirm_password: str) -> None:
    if new_password != confirm_password:
        raise AppError(422, "两次输入的新密码不一致", code="password_confirmation_mismatch")
    token_row = await repo.get_password_reset_token(session, token_hash=hash_session_token(token), now=datetime.now(UTC))
    if token_row is None:
        raise AppError(404, "重置链接无效或已过期", code="reset_token_invalid")
    user = await repo.get_user_by_id(session, token_row.user_id)
    if user is None:
        raise AppError(404, "未找到对应用户", code="user_not_found")
    user.password_hash = hash_password(new_password)
    await repo.delete_password_reset_token(session, token_hash=hash_session_token(token))
    await session.commit()


def build_oauth_entry(provider: str) -> dict:
    provider_name = provider.strip().lower()
    if provider_name not in {"google", "github"}:
        raise AppError(422, "不支持的 OAuth Provider", code="oauth_provider_unsupported")
    return {
        "provider": provider_name,
        "enabled": False,
        "reason": "当前环境未配置 OAuth provider 凭证，入口已预留。",
    }
