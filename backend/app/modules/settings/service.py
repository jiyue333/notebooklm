from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
from app.core.constant import PROVIDER_OLLAMA
from app.core.config import get_settings as get_system_settings
from app.infra.ai.factory import build_chat_model
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
    resolve_chat_runtime_config,
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


async def test_model_connection(
    *,
    user: User,
    payload: dict,
) -> dict:
    runtime_settings = get_system_settings()
    defaults = get_default_user_settings()
    merged = get_merged_user_settings(user)
    next_merged = {**merged}

    use_default = bool(payload.get("useDefaultModelConfig"))
    if use_default:
        next_merged["modelProvider"] = defaults["modelProvider"]
        next_merged["modelName"] = defaults["modelName"]
        next_merged["apiUrl"] = defaults["apiUrl"]
    else:
        if payload.get("modelProvider") is not None:
            next_merged["modelProvider"] = payload.get("modelProvider")
        if payload.get("modelName") is not None:
            next_merged["modelName"] = payload.get("modelName")
        if payload.get("apiUrl") is not None:
            next_merged["apiUrl"] = payload.get("apiUrl")

    provider = normalize_chat_provider(next_merged.get("modelProvider"))
    model_name = str(next_merged.get("modelName") or "").strip()
    api_url = str(next_merged.get("apiUrl") or "").strip()

    current_runtime = resolve_chat_runtime_config(user, runtime_settings)
    provided_api_key = str(payload.get("apiKey") or "").strip()
    clear_api_key = bool(payload.get("clearApiKey"))
    key_source = "missing"

    if provider == PROVIDER_OLLAMA:
        api_key = None
        key_source = "not_required"
    elif provided_api_key:
        api_key = provided_api_key
        key_source = "input"
    elif clear_api_key:
        api_key = None
        key_source = "missing"
    elif use_default:
        api_key = runtime_settings.default_chat_api_key
        key_source = "default" if api_key else "missing"
    else:
        api_key = current_runtime.api_key
        key_source = current_runtime.key_source

    if not model_name:
        raise AppError(422, "请先填写模型名称", code="model_test_model_required")
    if provider == PROVIDER_OLLAMA and not api_url:
        raise AppError(422, "请先填写 Ollama API 地址", code="model_test_api_url_required")
    if provider != PROVIDER_OLLAMA and not api_key:
        raise AppError(422, "请先填写 API Key", code="model_test_api_key_required")

    try:
        from langchain_core.messages import HumanMessage
    except Exception as exc:
        raise AppError(500, "测试连接依赖加载失败", code="model_test_dependency_error") from exc

    model = build_chat_model(
        provider=provider,
        model_name=model_name,
        base_url=api_url,
        api_key=api_key,
        timeout=float(min(runtime_settings.chat_model_timeout, 25)),
        max_output_tokens=64,
        metadata={"key_source": key_source, "test_connection": True},
    )

    started = perf_counter()
    try:
        response = await asyncio.wait_for(
            model.ainvoke([HumanMessage(content="请仅返回 pong")]),
            timeout=min(runtime_settings.chat_model_timeout, 25),
        )
    except asyncio.TimeoutError as exc:
        raise AppError(
            408,
            "模型连接超时，请检查模型服务或网络后重试",
            code="model_connection_test_timeout",
            meta={"provider": provider, "modelName": model_name},
        ) from exc
    except Exception as exc:
        raise AppError(
            422,
            f"模型连接测试失败：{str(exc)[:160]}",
            code="model_connection_test_failed",
            meta={"provider": provider, "modelName": model_name},
        ) from exc

    latency_ms = round((perf_counter() - started) * 1000, 2)
    preview = _flatten_model_probe_content(getattr(response, "content", ""))[:120]
    return {
        "ok": True,
        "provider": provider,
        "modelName": model_name,
        "apiUrl": api_url,
        "keySource": key_source,
        "latencyMs": latency_ms,
        "message": "模型连接测试成功",
        "preview": preview,
    }


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


def _flatten_model_probe_content(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if text:
                    parts.append(str(text))
        return "\n".join(parts).strip()
    return str(content or "").strip()


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
