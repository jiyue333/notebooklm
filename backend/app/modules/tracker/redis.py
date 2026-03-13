"""Redis 巡检 Tracker。

供 scheduler 周期执行，输出 bigkey / hotkey 巡检结果并同步更新低基数指标。
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from time import monotonic
from typing import Any

import structlog

from app.core.config import get_settings
from app.infra.cache.redis_client import get_redis_factory
from app.infra.telemetry.metrics import observe_redis_inspection

logger = structlog.get_logger(__name__)

_LAST_RUN_MONOTONIC = 0.0


@dataclass(slots=True)
class RedisInspectionEntry:
    key: str
    key_type: str
    bytes: int
    frequency: int | None = None


@dataclass(slots=True)
class RedisInspectionResult:
    ran: bool
    keys_scanned: int
    bigkeys: list[RedisInspectionEntry]
    hotkeys: list[RedisInspectionEntry]
    frequency_supported: bool
    generated_at: str

    @property
    def bigkey_count(self) -> int:
        return len(self.bigkeys)

    @property
    def hotkey_count(self) -> int:
        return len(self.hotkeys)

    @property
    def biggest_key_bytes(self) -> int:
        return max((item.bytes for item in self.bigkeys), default=0)

    @property
    def hottest_frequency(self) -> int:
        return max((item.frequency or 0 for item in self.hotkeys), default=0)


async def run_periodic_redis_inspection() -> RedisInspectionResult | None:
    global _LAST_RUN_MONOTONIC
    settings = get_settings()
    if not settings.redis_inspection_enabled:
        return None

    now = monotonic()
    if _LAST_RUN_MONOTONIC and now - _LAST_RUN_MONOTONIC < settings.redis_inspection_interval_seconds:
        return None
    _LAST_RUN_MONOTONIC = now

    try:
        result = await inspect_redis_keyspace()
    except Exception as exc:  # pragma: no cover - operational path
        observe_redis_inspection(result="error")
        logger.warning("redis.inspection_failed", error=str(exc))
        return RedisInspectionResult(
            ran=True,
            keys_scanned=0,
            bigkeys=[],
            hotkeys=[],
            frequency_supported=False,
            generated_at=datetime.now(UTC).isoformat(),
        )

    observe_redis_inspection(
        result="success",
        keys_scanned=result.keys_scanned,
        bigkey_count=result.bigkey_count,
        biggest_key_bytes=result.biggest_key_bytes,
        hotkey_count=result.hotkey_count,
        hottest_frequency=result.hottest_frequency,
        completed_at_unix=datetime.now(UTC).timestamp(),
    )
    return result


async def inspect_redis_keyspace() -> RedisInspectionResult:
    settings = get_settings()
    client = get_redis_factory().client
    cursor = 0
    scanned = 0
    bigkeys: list[RedisInspectionEntry] = []
    hotkeys: list[RedisInspectionEntry] = []
    frequency_supported = True

    while scanned < settings.redis_inspection_sample_limit:
        cursor, keys = await client.scan(
            cursor=cursor,
            count=min(settings.redis_inspection_scan_count, settings.redis_inspection_sample_limit - scanned),
        )
        for key in keys:
            decoded_key = _decode_key(key)
            key_type = _decode_key(await client.type(key))
            usage = int(await client.memory_usage(key) or 0)
            frequency = None
            if frequency_supported:
                try:
                    raw_frequency = await client.execute_command("OBJECT", "FREQ", key)
                    if raw_frequency is not None:
                        frequency = int(raw_frequency)
                except Exception:
                    frequency_supported = False
                    frequency = None

            if usage >= settings.redis_bigkey_threshold_bytes:
                bigkeys.append(
                    RedisInspectionEntry(
                        key=decoded_key,
                        key_type=key_type,
                        bytes=usage,
                        frequency=frequency,
                    )
                )
            if frequency is not None and frequency >= settings.redis_hotkey_frequency_threshold:
                hotkeys.append(
                    RedisInspectionEntry(
                        key=decoded_key,
                        key_type=key_type,
                        bytes=usage,
                        frequency=frequency,
                    )
                )
            scanned += 1
            if scanned >= settings.redis_inspection_sample_limit:
                break
        if cursor == 0:
            break

    bigkeys.sort(key=lambda item: item.bytes, reverse=True)
    hotkeys.sort(key=lambda item: item.frequency or 0, reverse=True)
    result = RedisInspectionResult(
        ran=True,
        keys_scanned=scanned,
        bigkeys=bigkeys[: settings.redis_inspection_top_n],
        hotkeys=hotkeys[: settings.redis_inspection_top_n],
        frequency_supported=frequency_supported,
        generated_at=datetime.now(UTC).isoformat(),
    )
    await asyncio.to_thread(_write_report, result)
    return result


def _decode_key(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _write_report(result: RedisInspectionResult) -> None:
    root = get_settings().redis_inspection_output_dir
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": result.generated_at,
        "keys_scanned": result.keys_scanned,
        "frequency_supported": result.frequency_supported,
        "bigkeys": [asdict(item) for item in result.bigkeys],
        "hotkeys": [asdict(item) for item in result.hotkeys],
    }
    latest_path = root / "inspection-latest.json"
    archive_path = root / f"inspection-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.json"
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    latest_path.write_text(serialized, encoding="utf-8")
    archive_path.write_text(serialized, encoding="utf-8")
