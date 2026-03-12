from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

import structlog

from app.core.config import get_settings
from app.infra.cache.redis_client import get_redis_factory

logger = structlog.get_logger(__name__)


def _is_cache_enabled() -> bool:
    return get_settings().redis_cache_enabled


def _json_default(value):
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


async def get_json(key: str) -> dict | list | str | int | float | bool | None:
    if not _is_cache_enabled():
        return None
    try:
        payload = await get_redis_factory().client.get(key)
    except Exception as exc:
        logger.warning("cache.redis_get_failed", key=key, error=str(exc))
        return None

    if payload is None:
        return None

    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")

    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        logger.warning("cache.redis_json_decode_failed", key=key)
        await delete_keys([key])
        return None


async def set_json(key: str, value, *, ttl_seconds: int) -> None:
    if not _is_cache_enabled():
        return
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            default=_json_default,
        )
        await get_redis_factory().client.set(key, payload.encode("utf-8"), ex=max(ttl_seconds, 1))
    except Exception as exc:
        logger.warning("cache.redis_set_failed", key=key, ttl_seconds=ttl_seconds, error=str(exc))


async def delete_keys(keys: Iterable[str]) -> None:
    if not _is_cache_enabled():
        return
    key_list = [key for key in keys if key]
    if not key_list:
        return
    try:
        await get_redis_factory().client.delete(*key_list)
    except Exception as exc:
        logger.warning("cache.redis_delete_failed", keys=key_list, error=str(exc))
