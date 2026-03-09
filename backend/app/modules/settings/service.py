from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.config import get_settings as get_system_settings
from app.modules.auth.models import User
from app.modules.auth.security import hash_password, verify_password
from app.modules.auth.service import build_user_view
from app.modules.jobs import publisher as job_publisher
from app.modules.jobs import repo as jobs_repo
from app.modules.notebooks.models import Article
from app.modules.settings.crypto import get_credential_crypto
from app.modules.settings import repo
from app.modules.settings.defaults import DEFAULT_USER_SETTINGS, SETTINGS_FIELDS
from app.modules.settings.runtime import (
    build_credential_state,
    get_merged_user_settings,
    normalize_chat_provider,
    normalize_embedding_provider,
    resolve_embedding_runtime_config,
)


def build_settings_view(user: User) -> dict:
    merged = get_merged_user_settings(user)
    system_settings = get_system_settings()
    chat_provider = normalize_chat_provider(merged["modelProvider"])
    embedding_provider = normalize_embedding_provider(merged.get("embeddingProvider"))
    chat_key_state = build_credential_state(
        ciphertext=user.llm_api_key_ciphertext,
        last4=user.llm_api_key_last4,
        default_key=system_settings.llm_default_api_key,
    )
    search_key_state = build_credential_state(
        ciphertext=user.exa_api_key_ciphertext,
        last4=user.exa_api_key_last4,
        default_key=system_settings.exa_default_api_key,
    )
    embedding_key_state = build_credential_state(
        ciphertext=user.embedding_api_key_ciphertext,
        last4=user.embedding_api_key_last4,
        default_key=system_settings.embedding_default_api_key,
    )
    if chat_provider == "ollama" and not chat_key_state["hasCustomKey"]:
        chat_key_state = {**chat_key_state, "hasEffectiveKey": False, "usingDefaultKey": False, "masked": ""}
    if embedding_provider == "ollama" and not embedding_key_state["hasCustomKey"]:
        embedding_key_state = {
            **embedding_key_state,
            "hasEffectiveKey": False,
            "usingDefaultKey": False,
            "masked": "",
        }
    return {
        "outputLanguage": merged["outputLanguage"],
        "themeColor": merged["themeColor"],
        "colorMode": merged["colorMode"],
        "modelProvider": chat_provider,
        "modelName": merged["modelName"],
        "apiUrl": merged["apiUrl"],
        "searchProvider": merged.get("searchProvider", "exa"),
        "embeddingProvider": embedding_provider,
        "embeddingModel": merged["embeddingModel"],
        "embeddingApiUrl": merged["embeddingApiUrl"],
        "hasApiKey": chat_key_state["hasEffectiveKey"],
        "hasCustomApiKey": chat_key_state["hasCustomKey"],
        "usingDefaultApiKey": chat_key_state["usingDefaultKey"],
        "apiKeyMasked": chat_key_state["masked"],
        "hasSearchApiKey": search_key_state["hasEffectiveKey"],
        "hasCustomSearchApiKey": search_key_state["hasCustomKey"],
        "usingDefaultSearchApiKey": search_key_state["usingDefaultKey"],
        "searchApiKeyMasked": search_key_state["masked"],
        "hasEmbeddingApiKey": embedding_key_state["hasEffectiveKey"],
        "hasCustomEmbeddingApiKey": embedding_key_state["hasCustomKey"],
        "usingDefaultEmbeddingApiKey": embedding_key_state["usingDefaultKey"],
        "embeddingApiKeyMasked": embedding_key_state["masked"],
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
    embedding_settings_changed = any(
        key in payload
        for key in {
            "embeddingProvider",
            "embeddingModel",
            "embeddingApiUrl",
            "embeddingApiKey",
            "clearEmbeddingApiKey",
        }
    )
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

    if payload.get("clearEmbeddingApiKey"):
        user.embedding_api_key_ciphertext = None
        user.embedding_api_key_last4 = None
        user.embedding_api_key_updated_at = now
    elif payload.get("embeddingApiKey"):
        embedding_api_key = payload["embeddingApiKey"].strip()
        user.embedding_api_key_ciphertext = crypto.encrypt(embedding_api_key)
        user.embedding_api_key_last4 = embedding_api_key[-4:]
        user.embedding_api_key_updated_at = now

    user.settings_json = settings_json
    reindex_jobs = []
    if embedding_settings_changed:
        reindex_jobs = await _schedule_embedding_reindex(session, user=user)
    await session.commit()
    if reindex_jobs:
        try:
            await job_publisher.publish_jobs(session, reindex_jobs)
            await session.commit()
        except Exception:
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


async def _schedule_embedding_reindex(session: AsyncSession, *, user: User) -> list:
    runtime_config = resolve_embedding_runtime_config(user)
    result = await session.execute(
        select(Article).where(
            Article.user_id == user.id,
            Article.clean_markdown.is_not(None),
        )
    )
    articles = list(result.scalars().all())
    jobs = []
    now = datetime.now(UTC)
    for article in articles:
        if (
            article.embedding_profile_key == runtime_config.profile_key
            and article.embedding_dimension is not None
        ):
            continue
        article.index_status = "stale"
        job = await jobs_repo.create_article_reindex_job(
            session,
            article_id=article.id,
            search_session_id=article.origin_search_session_id,
            dedupe_key=f"article_reindex:{article.id}:{runtime_config.profile_key}",
            payload_json={"articleId": article.id, "reason": "embedding_config_changed"},
            created_at=now,
        )
        jobs.append(job)
    return jobs
