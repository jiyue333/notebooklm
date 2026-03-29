from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.config import get_settings as get_system_settings
from app.infra.cache import (
    delete_keys,
    get_json,
    notebook_detail_key,
    set_json,
    settings_view_key,
)
from app.infra.security.credential_crypto import get_credential_crypto
from app.modules.auth.models import User
from app.modules.jobs import publisher as job_publisher
from app.modules.notebooks import repo as notebooks_repo
from app.modules.settings.defaults import get_default_user_settings
from app.modules.settings.patcher import apply_credential_updates, merge_settings_payload
from app.modules.settings.reindex import (
    clear_existing_embeddings,
    count_reindexable_articles,
    schedule_embedding_reindex,
)
from app.modules.settings.runtime import (
    get_merged_user_settings,
    normalize_chat_provider,
    normalize_embedding_provider,
    resolve_embedding_profile_key_from_merged,
    resolve_embedding_runtime_config_from_merged,
)
from app.modules.settings.view_builder import build_settings_view

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class EmbeddingUpdatePlan:
    changed: bool
    next_profile_key: str
    next_runtime: object


async def get_settings(user: User) -> dict:
    cache_key = settings_view_key(user_id=user.id)
    cached = await get_json(cache_key)
    if isinstance(cached, dict):
        return cached

    item = build_settings_view(user)
    await set_json(
        cache_key,
        item,
        ttl_seconds=get_system_settings().cache_ttl_settings_seconds,
    )
    return item


async def update_settings(
    session: AsyncSession,
    *,
    user: User,
    payload: dict,
) -> dict:
    settings_json, effective_settings_json = _merge_user_settings(user=user, payload=payload)
    settings_json = _normalize_provider_fields(settings_json)
    effective_settings_json = _normalize_provider_fields(effective_settings_json)

    embedding_update = _build_embedding_update_plan(user=user, effective_settings_json=effective_settings_json)
    await _ensure_embedding_reindex_confirmed(
        session,
        user=user,
        payload=payload,
        embedding_update=embedding_update,
    )

    crypto = get_credential_crypto()
    now = datetime.now(UTC)
    apply_credential_updates(user=user, payload=payload, crypto=crypto, now=now)
    _apply_miniflux_token_updates(settings_json=settings_json, payload=payload, crypto=crypto)
    user.settings_json = settings_json
    reindex_jobs = await _schedule_embedding_update_jobs(
        session,
        user=user,
        embedding_update=embedding_update,
    )
    await session.commit()
    await _publish_reindex_jobs(session, reindex_jobs)
    await session.refresh(user)
    await invalidate_settings_view_cache(user_id=user.id)
    await _invalidate_user_notebook_detail_caches(session, user_id=user.id, embedding_changed=embedding_update.changed)
    item = build_settings_view(user)
    await set_json(
        settings_view_key(user_id=user.id),
        item,
        ttl_seconds=get_system_settings().cache_ttl_settings_seconds,
    )
    return item


def _merge_user_settings(*, user: User, payload: dict) -> tuple[dict, dict]:
    return merge_settings_payload(
        stored_settings={**(user.settings_json or {})},
        payload=payload,
        default_settings=get_default_user_settings(),
    )

def _normalize_provider_fields(settings_json: dict) -> dict:
    normalized = {**settings_json}
    if "modelProvider" in normalized:
        normalized["modelProvider"] = normalize_chat_provider(normalized.get("modelProvider"))
    if "embeddingProvider" in normalized:
        normalized["embeddingProvider"] = normalize_embedding_provider(normalized.get("embeddingProvider"))
    return normalized


def _apply_miniflux_token_updates(*, settings_json: dict, payload: dict, crypto) -> None:
    if payload.get("clearMinifluxApiToken"):
        settings_json.pop("minifluxApiToken", None)
        settings_json.pop("minifluxApiTokenLast4", None)
        return

    raw_token = payload.get("minifluxApiToken")
    if not raw_token:
        return

    token = str(raw_token).strip()
    if not token:
        return

    settings_json["minifluxApiToken"] = crypto.encrypt(token)
    settings_json["minifluxApiTokenLast4"] = token[-4:]


def _build_embedding_update_plan(*, user: User, effective_settings_json: dict) -> EmbeddingUpdatePlan:
    current_profile_key = resolve_embedding_profile_key_from_merged(
        merged=get_merged_user_settings(user),
    )
    next_profile_key = resolve_embedding_profile_key_from_merged(
        merged=effective_settings_json,
    )
    return EmbeddingUpdatePlan(
        changed=current_profile_key != next_profile_key,
        next_profile_key=next_profile_key,
        next_runtime=resolve_embedding_runtime_config_from_merged(
            merged=effective_settings_json,
            user=user,
        ),
    )


async def _ensure_embedding_reindex_confirmed(
    session: AsyncSession,
    *,
    user: User,
    payload: dict,
    embedding_update: EmbeddingUpdatePlan,
) -> None:
    if not embedding_update.changed:
        return

    affected_article_count = await count_reindexable_articles(session, user=user)
    if affected_article_count <= 0 or payload.get("confirmEmbeddingReindex"):
        return

    raise AppError(
        409,
        "修改 Embedding 配置会清空旧向量并自动重建索引，请确认后继续。",
        code="embedding_reindex_confirmation_required",
        meta={
            "affectedArticleCount": affected_article_count,
            "nextEmbeddingProfileKey": embedding_update.next_profile_key,
        },
    )


async def _schedule_embedding_update_jobs(
    session: AsyncSession,
    *,
    user: User,
    embedding_update: EmbeddingUpdatePlan,
) -> list:
    if not embedding_update.changed:
        return []

    await clear_existing_embeddings(session, user=user, next_runtime=embedding_update.next_runtime)
    return await schedule_embedding_reindex(
        session,
        user=user,
        runtime_config=embedding_update.next_runtime,
    )


async def _publish_reindex_jobs(session: AsyncSession, jobs: list) -> None:
    if not jobs:
        return
    try:
        await job_publisher.publish_jobs(session, jobs)
    except Exception:
        logger.exception("settings.reindex_jobs_publish_failed", job_count=len(jobs))
    finally:
        await session.commit()


async def invalidate_settings_view_cache(*, user_id: str) -> None:
    await delete_keys([settings_view_key(user_id=user_id)])


async def _invalidate_user_notebook_detail_caches(
    session: AsyncSession,
    *,
    user_id: str,
    embedding_changed: bool,
) -> None:
    if not embedding_changed:
        return
    notebooks = await notebooks_repo.list_notebooks(session, user_id=user_id)
    await delete_keys(
        [
            notebook_detail_key(user_id=user_id, notebook_id=notebook.id)
            for notebook in notebooks
        ]
    )
