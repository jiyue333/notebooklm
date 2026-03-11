from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.infra.security.credential_crypto import get_credential_crypto
from app.modules.auth.models import User
from app.modules.jobs import publisher as job_publisher
from app.modules.settings.defaults import get_default_user_settings
from app.modules.settings.patcher import apply_credential_updates, merge_settings_payload
from app.modules.settings.reindex import (
    clear_existing_embeddings,
    count_reindexable_articles,
    schedule_embedding_reindex,
)
from app.modules.settings.runtime import (
    get_merged_user_settings,
    resolve_embedding_profile_key_from_merged,
    resolve_embedding_runtime_config_from_merged,
)
from app.modules.settings.view_builder import build_settings_view


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
    settings_json, effective_settings_json = merge_settings_payload(
        stored_settings=stored_settings,
        payload=payload,
        default_settings=default_settings,
    )

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
        affected_article_count = await count_reindexable_articles(session, user=user)
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
    apply_credential_updates(user=user, payload=payload, crypto=crypto, now=now)

    user.settings_json = settings_json
    reindex_jobs = []
    if embedding_profile_changed:
        await clear_existing_embeddings(session, user=user, next_runtime=next_embedding_runtime)
        reindex_jobs = await schedule_embedding_reindex(
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
