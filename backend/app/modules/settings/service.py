from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.modules.auth.models import User
from app.modules.auth.security import hash_password, verify_password
from app.modules.auth.service import build_user_view
from app.modules.settings.crypto import get_credential_crypto
from app.modules.settings.defaults import DEFAULT_USER_SETTINGS, SETTINGS_FIELDS
from app.modules.settings import repo


def _mask_last4(last4: str | None) -> str:
    return f"••••{last4}" if last4 else ""


def build_settings_view(user: User) -> dict:
    merged = {**DEFAULT_USER_SETTINGS, **(user.settings_json or {})}
    return {
        "outputLanguage": merged["outputLanguage"],
        "themeColor": merged["themeColor"],
        "colorMode": merged["colorMode"],
        "modelProvider": merged["modelProvider"],
        "modelName": merged["modelName"],
        "apiUrl": merged["apiUrl"],
        "searchProvider": merged.get("searchProvider", "exa"),
        "hasApiKey": bool(user.llm_api_key_ciphertext),
        "apiKeyMasked": _mask_last4(user.llm_api_key_last4),
        "hasSearchApiKey": bool(user.exa_api_key_ciphertext),
        "searchApiKeyMasked": _mask_last4(user.exa_api_key_last4),
        "username": user.name,
    }


async def get_settings(user: User) -> dict:
    return build_settings_view(user)


async def update_settings(
    session: AsyncSession,
    *,
    user: User,
    payload: dict,
) -> dict:
    settings_json = {**DEFAULT_USER_SETTINGS, **(user.settings_json or {})}
    for field in SETTINGS_FIELDS:
        if field in payload and payload[field] is not None:
            settings_json[field] = payload[field]

    if settings_json.get("searchProvider") != "exa":
        raise AppError(422, "当前仅支持 Exa 作为搜索 Provider", code="invalid_search_provider")

    crypto = get_credential_crypto()
    now = datetime.now(UTC)

    if payload.get("clearApiKey"):
        user.llm_api_key_ciphertext = None
        user.llm_api_key_last4 = None
        user.llm_api_key_updated_at = now
    elif payload.get("apiKey"):
        api_key = payload["apiKey"].strip()
        user.llm_api_key_ciphertext = crypto.encrypt(api_key)
        user.llm_api_key_last4 = api_key[-4:]
        user.llm_api_key_updated_at = now

    if payload.get("clearSearchApiKey"):
        user.exa_api_key_ciphertext = None
        user.exa_api_key_last4 = None
        user.exa_api_key_updated_at = now
    elif payload.get("searchApiKey"):
        search_api_key = payload["searchApiKey"].strip()
        user.exa_api_key_ciphertext = crypto.encrypt(search_api_key)
        user.exa_api_key_last4 = search_api_key[-4:]
        user.exa_api_key_updated_at = now

    user.settings_json = settings_json
    await session.commit()
    await session.refresh(user)
    return build_settings_view(user)


async def update_profile(session: AsyncSession, *, user: User, username: str) -> dict:
    normalized_username = username.strip()
    existing = await repo.get_user_by_name(session, normalized_username)
    if existing is not None and existing.id != user.id:
        raise AppError(409, "用户名已存在", code="username_conflict")

    user.name = normalized_username
    await session.commit()
    await session.refresh(user)
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
