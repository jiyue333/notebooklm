from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.config import get_settings as get_system_settings
from app.modules.auth import repo as auth_repo
from app.modules.auth.models import User
from app.modules.auth.security import hash_password, verify_password
from app.modules.auth.service import build_user_view
from app.modules.jobs import publisher as job_publisher
from app.modules.jobs import repo as jobs_repo
from app.modules.notebooks.models import Article, ArticleChunk
from app.modules.settings.crypto import get_credential_crypto
from app.modules.settings.defaults import SETTINGS_FIELDS, get_default_user_settings
from app.modules.settings.runtime import (
    build_credential_state,
    get_merged_user_settings,
    normalize_chat_provider,
    normalize_embedding_provider,
    resolve_embedding_profile_key_from_merged,
    resolve_embedding_runtime_config_from_merged,
)

MODEL_SETTINGS_FIELDS = ("modelProvider", "modelName", "apiUrl")
SEARCH_SETTINGS_FIELDS = ("searchProvider",)
EMBEDDING_SETTINGS_FIELDS = ("embeddingProvider", "embeddingModel", "embeddingApiUrl")


def build_settings_view(user: User) -> dict:
    merged = get_merged_user_settings(user)
    user_settings = user.settings_json or {}
    system_settings = get_system_settings()
    default_settings = get_default_user_settings()
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
        "usingDefaultModelConfig": not any(field in user_settings for field in {"modelProvider", "modelName", "apiUrl"}),
        "defaultModelProvider": default_settings["modelProvider"],
        "defaultModelName": default_settings["modelName"],
        "defaultApiUrl": default_settings["apiUrl"],
        "embeddingProvider": embedding_provider,
        "embeddingModel": merged["embeddingModel"],
        "embeddingApiUrl": merged["embeddingApiUrl"],
        "usingDefaultSearchConfig": "searchProvider" not in user_settings,
        "defaultSearchProvider": default_settings["searchProvider"],
        "usingDefaultEmbeddingConfig": not any(
            field in user_settings for field in {"embeddingProvider", "embeddingModel", "embeddingApiUrl"}
        ),
        "defaultEmbeddingProvider": default_settings["embeddingProvider"],
        "defaultEmbeddingModel": default_settings["embeddingModel"],
        "defaultEmbeddingApiUrl": default_settings["embeddingApiUrl"],
        "embeddingOutputDimensions": system_settings.embedding_output_dimensions,
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
    default_settings = get_default_user_settings()
    stored_settings = {**(user.settings_json or {})}
    settings_json = {**stored_settings}
    use_default_model_config = bool(payload.get("useDefaultModelConfig"))
    use_default_search_config = bool(payload.get("useDefaultSearchConfig"))
    use_default_embedding_config = bool(payload.get("useDefaultEmbeddingConfig"))

    for field in SETTINGS_FIELDS:
        if use_default_model_config and field in MODEL_SETTINGS_FIELDS:
            continue
        if use_default_search_config and field in SEARCH_SETTINGS_FIELDS:
            continue
        if use_default_embedding_config and field in EMBEDDING_SETTINGS_FIELDS:
            continue
        if field in payload and payload[field] is not None:
            settings_json[field] = payload[field]

    if use_default_model_config:
        _drop_settings_fields(settings_json, MODEL_SETTINGS_FIELDS)
    if use_default_search_config:
        _drop_settings_fields(settings_json, SEARCH_SETTINGS_FIELDS)
    if use_default_embedding_config:
        _drop_settings_fields(settings_json, EMBEDDING_SETTINGS_FIELDS)

    effective_settings_json = {**default_settings, **settings_json}

    if effective_settings_json.get("searchProvider") != "exa":
        raise AppError(422, "当前仅支持 Exa 作为搜索 Provider", code="invalid_search_provider")

    current_embedding_profile_key = resolve_embedding_profile_key_from_merged(
        merged=get_merged_user_settings(user),
    )
    next_embedding_profile_key = resolve_embedding_profile_key_from_merged(
        merged=effective_settings_json,
    )
    next_embedding_runtime = resolve_embedding_runtime_config_from_merged(
        merged=effective_settings_json,
        user=user,
    )
    embedding_profile_changed = current_embedding_profile_key != next_embedding_profile_key

    if embedding_profile_changed:
        affected_article_count = await _count_reindexable_articles(session, user=user)
        if affected_article_count > 0 and not payload.get("confirmEmbeddingReindex"):
            raise AppError(
                409,
                "修改 Embedding 配置会清空旧向量并自动重建索引，请确认后继续。",
                code="embedding_reindex_confirmation_required",
                meta={
                    "affectedArticleCount": affected_article_count,
                    "nextEmbeddingProfileKey": next_embedding_profile_key,
                },
            )

    crypto = get_credential_crypto()
    now = datetime.now(UTC)

    if use_default_model_config or payload.get("clearApiKey"):
        user.llm_api_key_ciphertext = None
        user.llm_api_key_last4 = None
        user.llm_api_key_updated_at = now
    elif payload.get("apiKey"):
        api_key = payload["apiKey"].strip()
        user.llm_api_key_ciphertext = crypto.encrypt(api_key)
        user.llm_api_key_last4 = api_key[-4:]
        user.llm_api_key_updated_at = now

    if use_default_search_config or payload.get("clearSearchApiKey"):
        user.exa_api_key_ciphertext = None
        user.exa_api_key_last4 = None
        user.exa_api_key_updated_at = now
    elif payload.get("searchApiKey"):
        search_api_key = payload["searchApiKey"].strip()
        user.exa_api_key_ciphertext = crypto.encrypt(search_api_key)
        user.exa_api_key_last4 = search_api_key[-4:]
        user.exa_api_key_updated_at = now

    if use_default_embedding_config or payload.get("clearEmbeddingApiKey"):
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
    if embedding_profile_changed:
        await _clear_existing_embeddings(session, user=user, next_runtime=next_embedding_runtime)
        reindex_jobs = await _schedule_embedding_reindex(
            session,
            user=user,
            runtime_config=next_embedding_runtime,
        )
    await session.commit()
    if reindex_jobs:
        try:
            await job_publisher.publish_jobs(session, reindex_jobs)
            await session.commit()
        except Exception:
            await session.commit()
    await session.refresh(user)
    return build_settings_view(user)


def _drop_settings_fields(settings_json: dict, fields: tuple[str, ...]) -> None:
    for field in fields:
        settings_json.pop(field, None)


async def update_profile(session: AsyncSession, *, user: User, username: str) -> dict:
    normalized_username = username.strip()
    existing = await auth_repo.get_user_by_name(session, normalized_username)
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


async def _count_reindexable_articles(session: AsyncSession, *, user: User) -> int:
    result = await session.execute(
        select(Article.id).where(
            Article.user_id == user.id,
            Article.clean_markdown.is_not(None),
        )
    )
    return len(list(result.scalars().all()))


async def _clear_existing_embeddings(
    session: AsyncSession,
    *,
    user: User,
    next_runtime,
) -> None:
    article_result = await session.execute(
        select(Article.id).where(
            Article.user_id == user.id,
            Article.clean_markdown.is_not(None),
        )
    )
    article_ids = list(article_result.scalars().all())
    if not article_ids:
        return

    await session.execute(
        update(Article)
        .where(Article.id.in_(article_ids))
        .values(
            article_vector=None,
            embedding_provider=next_runtime.provider,
            embedding_model=next_runtime.model_name,
            embedding_profile_key=next_runtime.profile_key,
            embedding_dimension=None,
            index_status="stale",
            chunk_status="stale",
        )
    )
    await session.execute(delete(ArticleChunk).where(ArticleChunk.article_id.in_(article_ids)))


async def _schedule_embedding_reindex(session: AsyncSession, *, user: User, runtime_config) -> list:
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
