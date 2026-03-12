from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(slots=True)
class EmbeddingUpdatePlan:
    changed: bool
    next_profile_key: str
    next_runtime: object


async def get_settings(user: User) -> dict:
    return build_settings_view(user)


async def update_settings(
    session: AsyncSession,
    *,
    user: User,
    payload: dict,
) -> dict:
    settings_json, effective_settings_json = _merge_user_settings(user=user, payload=payload)
    _validate_search_provider(effective_settings_json)

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
    user.settings_json = settings_json
    reindex_jobs = await _schedule_embedding_update_jobs(
        session,
        user=user,
        embedding_update=embedding_update,
    )
    await session.commit()
    await _publish_reindex_jobs(session, reindex_jobs)
    await session.refresh(user)
    return build_settings_view(user)


def _merge_user_settings(*, user: User, payload: dict) -> tuple[dict, dict]:
    return merge_settings_payload(
        stored_settings={**(user.settings_json or {})},
        payload=payload,
        default_settings=get_default_user_settings(),
    )


def _validate_search_provider(effective_settings_json: dict) -> None:
    if effective_settings_json.get("searchProvider") != "exa":
        raise AppError(422, "当前仅支持 Exa 作为搜索 Provider", code="invalid_search_provider")


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
        pass
    finally:
        await session.commit()
